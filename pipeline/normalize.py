"""Normalización de leads, asesores e histórico (RF-02, TRD 6 y 6.1).

Cada valor que cambia o se descarta queda registrado en el colector de calidad.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime, time
from functools import partial

import pandas as pd

from pipeline.config import VENTANA_FIN, VENTANA_INICIO, ZONA
from pipeline.quality import ColectorCalidad

ARCHIVO_LEADS = "leads.csv"

CANALES = {"whatsapp": "WhatsApp", "meta ads": "Meta Ads", "formulario web": "Formulario Web"}
ESTADOS = {
    "sin gestion": "Sin gestión",
    "no contesta": "No contesta",
    "contactado": "Contactado",
    "en proceso": "En proceso",
    "cotizacion enviada": "Cotización enviada",
    "descartado": "Descartado",
}
# Claves sin tildes y en minúsculas -> nombre oficial. Incluye los sinónimos de TRD 6.
CIUDADES = {
    "barranquilla": "Barranquilla",
    "b/quilla": "Barranquilla",
    "santa marta": "Santa Marta",
    "sta marta": "Santa Marta",
    "rionegro": "Rionegro",
    "rio negro": "Rionegro",
    "bogota": "Bogotá D.C.",
    "bogota dc": "Bogotá D.C.",
    "bogota d.c.": "Bogotá D.C.",
    "cartagena": "Cartagena",
    "cartagena de indias": "Cartagena",
    "medellin": "Medellín",
    "itagui": "Itagüí",
    "monteria": "Montería",
    "bello": "Bello",
    "soledad": "Soledad",
    "soacha": "Soacha",
}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Campos simples
# ---------------------------------------------------------------------------
def es_nulo(valor: object) -> bool:
    """True para None, NaN o texto vacío."""
    if valor is None:
        return True
    if isinstance(valor, float) and math.isnan(valor):
        return True
    return isinstance(valor, str) and not valor.strip()


def clave_texto(valor: object) -> str | None:
    """Minúsculas, sin tildes y sin espacios sobrantes. None si el valor es nulo."""
    if es_nulo(valor):
        return None
    descompuesto = unicodedata.normalize("NFKD", str(valor))
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return " ".join(sin_tildes.lower().split())


def normalizar_canal(valor: object) -> str | None:
    return CANALES.get(clave_texto(valor))


def normalizar_estado(valor: object) -> str | None:
    return ESTADOS.get(clave_texto(valor))


def normalizar_telefono(valor: object) -> str | None:
    """Solo dígitos; quita el prefijo 57; válido si tiene 10 dígitos y empieza por 3."""
    if es_nulo(valor):
        return None
    digitos = re.sub(r"\D", "", str(valor))
    if len(digitos) == 12 and digitos.startswith("57"):
        digitos = digitos[2:]
    return digitos if len(digitos) == 10 and digitos.startswith("3") else None


def normalizar_email(valor: object) -> str | None:
    """`strip().lower()` y validación básica de formato."""
    if es_nulo(valor):
        return None
    email = str(valor).strip().lower()
    return email if _EMAIL.match(email) else None


def normalizar_nombre(valor: object) -> str:
    """Sin espacios sobrantes y en formato título."""
    return "" if es_nulo(valor) else " ".join(str(valor).split()).title()


def normalizar_ciudad(valor: object) -> str | None:
    """Nombre oficial según el diccionario; si no está, el texto limpio en formato título."""
    clave = clave_texto(valor)
    if clave is None:
        return None
    return CIUDADES.get(clave, " ".join(str(valor).split()).title())


# ---------------------------------------------------------------------------
# Fechas (TRD 6.1)
# ---------------------------------------------------------------------------
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$")
_DIA = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
_BARRAS = re.compile(r"^(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2})$")


def _crear(anio: int, mes: int, dia: int, hora: int = 0, minuto: int = 0) -> datetime | None:
    try:
        return datetime(anio, mes, dia, hora, minuto)
    except ValueError:  # fecha imposible, p. ej. 2026-08-33
        return None


def lecturas_fecha(valor: object) -> tuple[list[tuple[datetime, str]], str | None]:
    """Lecturas válidas posibles [(fecha, orden)] y precisión ('minuto', 'dia' o None si no se reconoce).

    `orden` es 'ddmm' o 'mmdd' para el formato con barras y 'unica' para los demás.
    """
    if es_nulo(valor):
        return [], None
    texto = str(valor).strip()
    if m := _ISO.match(texto):
        a, mes, d, h, mi, _ = map(int, m.groups())
        fecha = _crear(a, mes, d, h, mi)
        return ([(fecha, "unica")] if fecha else []), "minuto"
    if m := _DIA.match(texto):
        d, mes, a = map(int, m.groups())
        fecha = _crear(a, mes, d)
        return ([(fecha, "unica")] if fecha else []), "dia"
    if m := _BARRAS.match(texto):
        x, y, a, h, mi = map(int, m.groups())
        opciones = []
        ddmm, mmdd = _crear(a, y, x, h, mi), _crear(a, x, y, h, mi)
        if ddmm:
            opciones.append((ddmm, "ddmm"))
        if mmdd and mmdd != ddmm:
            opciones.append((mmdd, "mmdd"))
        return opciones, "minuto"
    return [], None


def _en_ventana(fecha: datetime) -> bool:
    return VENTANA_INICIO <= fecha.date() <= VENTANA_FIN


def resolver_fecha(valor: object, otra: object, es_registro: bool) -> tuple[datetime | None, str]:
    """Aplica la regla 6.1 y devuelve (fecha sin zona horaria, motivo).

    Motivos: vacia, invalida, unica, componente_mayor_12, ventana, coherencia, por_defecto.
    """
    if es_nulo(valor):
        return None, "vacia"
    opciones, precision = lecturas_fecha(valor)
    if not opciones:
        return None, "invalida"
    if len(opciones) == 1:
        fecha, orden = opciones[0]
        return fecha, ("unica" if orden == "unica" else "componente_mayor_12")

    # Paso 2: descartar lecturas fuera de la ventana de datos.
    en_ventana = [o for o in opciones if _en_ventana(o[0])]
    if len(en_ventana) == 1:
        return en_ventana[0][0], "ventana"
    candidatas = en_ventana or opciones

    # Paso 3: coherencia con la otra fecha (registro <= primer contacto).
    otras, precision_otra = lecturas_fecha(otra)
    otras = [o for o in otras if _en_ventana(o[0])] or otras
    if otras:
        por_dia = "dia" in (precision, precision_otra)
        coherentes = []
        for fecha, orden in candidatas:
            for fecha_otra, _ in otras:
                a, b = (fecha.date(), fecha_otra.date()) if por_dia else (fecha, fecha_otra)
                if (a <= b) if es_registro else (a >= b):
                    coherentes.append((fecha, orden))
                    break
        if len(coherentes) == 1:
            return coherentes[0][0], "coherencia"

    # Paso 4: empate -> dd/mm, convención colombiana.
    return next(f for f, orden in candidatas if orden == "ddmm"), "por_defecto"


def a_bogota(fecha: datetime | None) -> datetime | None:
    """Asigna la zona horaria de Colombia a una fecha sin zona."""
    return None if fecha is None else fecha.replace(tzinfo=ZONA)


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------
def _registrar_fecha(colector, lead_id, empresa, campo, valor, motivo) -> None:
    """Registra solo los casos que requieren atención: ambiguas resueltas e inválidas."""
    if motivo in ("ventana", "coherencia"):
        colector.registrar(
            ARCHIVO_LEADS,
            lead_id,
            campo,
            "formato_fecha_ambiguo",
            valor,
            f"resuelta por {motivo}",
            empresa,
        )
    elif motivo == "por_defecto":
        colector.registrar(
            ARCHIVO_LEADS,
            lead_id,
            campo,
            "fecha_ambigua_resuelta_por_defecto",
            valor,
            "se usa dd/mm",
            empresa,
        )
    elif motivo == "invalida":
        colector.registrar(ARCHIVO_LEADS, lead_id, campo, "fecha_invalida", valor, "se guarda nula", empresa)  # fmt: skip


def normalizar_leads(crudos: pd.DataFrame, colector: ColectorCalidad) -> pd.DataFrame:
    """Normaliza leads.csv: excluye repetidos y registros de prueba, y registra cada corrección."""
    filas = []
    vistos: set[str] = set()
    for r in crudos.itertuples(index=False):
        lead_id, empresa = r.lead_id, r.empresa_id
        # anotar(campo, tipo, valor, accion): registra un problema de este lead.
        anotar = partial(colector.registrar, ARCHIVO_LEADS, lead_id, empresa_id=empresa)

        if lead_id in vistos:
            anotar("lead_id", "lead_repetido", lead_id, "se conserva la primera fila")
            continue
        vistos.add(lead_id)

        canal = normalizar_canal(r.canal)
        telefono = normalizar_telefono(r.telefono)
        nombre_original = "" if es_nulo(r.nombre_cliente) else str(r.nombre_cliente)
        if "prueba" in nombre_original.lower() or (telefono is None and canal is None):
            anotar("nombre_cliente", "registro_prueba", nombre_original, "excluido")
            continue
        if canal is None:
            anotar("canal", "canal_invalido", r.canal, "excluido: el canal es obligatorio")
            continue
        if canal != r.canal:
            anotar("canal", "canal_no_estandar", r.canal, f"normalizado a {canal}")

        estado = normalizar_estado(r.estado_gestion)
        if estado is None:
            anotar("estado_gestion", "estado_desconocido", r.estado_gestion, "se asume Sin gestión")
            estado = "Sin gestión"
        elif estado != r.estado_gestion:
            anotar(
                "estado_gestion", "estado_no_estandar", r.estado_gestion, f"normalizado a {estado}"
            )

        if telefono is None:
            anotar(
                "telefono",
                "telefono_invalido",
                r.telefono,
                "se guarda nulo; clave secundaria por email",
            )
        elif telefono != r.telefono:
            anotar("telefono", "telefono_formato", r.telefono, "solo dígitos, sin prefijo 57")

        email = normalizar_email(r.email)
        if not es_nulo(r.email) and email is None:
            anotar("email", "email_invalido", r.email, "se guarda nulo")
        elif email is not None and email != r.email:
            anotar("email", "email_normalizado", r.email, "strip y minúsculas")

        nombre = normalizar_nombre(r.nombre_cliente)
        if nombre != nombre_original:
            anotar(
                "nombre_cliente", "nombre_normalizado", nombre_original, "espacios y formato título"
            )

        ciudad = normalizar_ciudad(r.ciudad)
        if ciudad is not None and ciudad != r.ciudad:
            anotar("ciudad", "ciudad_normalizada", r.ciudad, f"normalizada a {ciudad}")

        registro, motivo_r = resolver_fecha(
            r.fecha_registro, r.fecha_primer_contacto, es_registro=True
        )
        contacto, motivo_c = resolver_fecha(
            r.fecha_primer_contacto, r.fecha_registro, es_registro=False
        )
        _registrar_fecha(colector, lead_id, empresa, "fecha_registro", r.fecha_registro, motivo_r)
        _registrar_fecha(
            colector, lead_id, empresa, "fecha_primer_contacto", r.fecha_primer_contacto, motivo_c
        )
        precision_r = lecturas_fecha(r.fecha_registro)[1] if registro else None
        precision_c = lecturas_fecha(r.fecha_primer_contacto)[1] if contacto else None

        # Validaciones cruzadas: solo banderas, no descartan.
        if registro and contacto:
            por_dia = "dia" in (precision_r, precision_c)
            if (contacto.date() < registro.date()) if por_dia else (contacto < registro):
                anotar(
                    "fecha_primer_contacto",
                    "contacto_antes_de_registro",
                    r.fecha_primer_contacto,
                    "bandera",
                )
        if estado != "Sin gestión" and contacto is None:
            anotar("fecha_primer_contacto", "estado_sin_fecha_contacto", estado, "bandera")
        if estado == "Sin gestión" and contacto is not None:
            anotar(
                "fecha_primer_contacto",
                "sin_gestion_con_contacto",
                r.fecha_primer_contacto,
                "bandera",
            )

        filas.append({
            "lead_id": lead_id,
            "empresa_id": empresa,
            "punto_venta_id": r.punto_venta_id,
            "canal": canal,
            "campania": None if es_nulo(r.campania) else str(r.campania).strip(),
            "fecha_registro": a_bogota(registro),
            "fecha_registro_precision": precision_r,
            "fecha_primer_contacto": a_bogota(contacto),
            "fecha_contacto_precision": precision_c,
            "estado_gestion": estado,
            "nombre": nombre,
            "telefono": telefono,
            "email": email,
            "ciudad": ciudad,
            "modelo_texto_original": None if es_nulo(r.modelo_interes_texto) else str(r.modelo_interes_texto).strip(),
        })  # fmt: skip
    # dtype object: conserva None en lugar de NaN o NaT, así las comprobaciones son explícitas.
    return pd.DataFrame(filas, dtype="object")


def validar_conversaciones(
    leads: pd.DataFrame, conversaciones: list[dict], colector: ColectorCalidad
) -> None:
    """Registra conversaciones huérfanas y conversaciones que empiezan antes del registro del lead."""
    registros = dict(zip(leads["lead_id"], leads["fecha_registro"], strict=True))
    empresas = dict(zip(leads["lead_id"], leads["empresa_id"], strict=True))
    for c in conversaciones:
        lead_id = c["lead_id"]
        if lead_id not in registros:
            colector.registrar(
                "conversaciones.json",
                c["conversacion_id"],
                "lead_id",
                "conversacion_huerfana",
                lead_id,
                "se carga sin empresa",
            )
            continue
        inicio = resolver_fecha(c["fecha_inicio"], None, es_registro=False)[0]
        registro = registros[lead_id]
        if inicio and registro and inicio.date() < registro.date():
            colector.registrar(ARCHIVO_LEADS, lead_id, "fecha_registro", "conversacion_antes_de_registro", c["conversacion_id"], "bandera", empresas[lead_id])  # fmt: skip


# ---------------------------------------------------------------------------
# Asesores e histórico
# ---------------------------------------------------------------------------
def normalizar_asesores(crudos: pd.DataFrame) -> pd.DataFrame:
    """Renombra la capacidad (TRD 5.1) y convierte tipos."""
    return pd.DataFrame(
        {
            "asesor_id": crudos["asesor_id"].str.strip(),
            "empresa_id": crudos["empresa_id"].str.strip(),
            "punto_venta_id": crudos["punto_venta_id"].str.strip(),
            "nombre": crudos["nombre"].map(normalizar_nombre),
            "capacidad_diaria": crudos["capacidad_diaria_leads"].astype(int),
            "activo": crudos["activo"].str.strip().str.upper().eq("SI"),
            "fecha_ingreso": crudos["fecha_ingreso"].map(lambda v: None if es_nulo(v) else date.fromisoformat(v)),
        },
        dtype="object",
    )  # fmt: skip


def normalizar_historico(crudos: pd.DataFrame) -> pd.DataFrame:
    """Convierte tipos del histórico; sus valores ya vienen en formato estándar."""
    return pd.DataFrame(
        {
            "lead_id": crudos["lead_id"],
            "fecha_registro": crudos["fecha_registro"].map(date.fromisoformat),
            "canal": crudos["canal"].map(normalizar_canal),
            "empresa_id": crudos["empresa_id"],
            "punto_venta_id": crudos["punto_venta_id"],
            "modelo_cotizado": crudos["modelo_cotizado"],
            "precio_lista": crudos["precio_lista"].astype(int),
            "horas_al_primer_contacto": crudos["horas_al_primer_contacto"].map(lambda v: None if es_nulo(v) else float(v)),
            "numero_contactos": crudos["numero_contactos"].astype(int),
            "manifesto_cuota_inicial": crudos["manifesto_cuota_inicial"],
            "forma_pago_declarada": crudos["forma_pago_declarada"],
            "pidio_cita": crudos["pidio_cita"].eq("SI"),
            "desenlace": crudos["desenlace"],
        },
        dtype="object",
    )  # fmt: skip


def hora_mensaje(valor: object) -> time | None:
    """Hora de un mensaje ('16:55'), o None si no se puede leer."""
    try:
        return time.fromisoformat(str(valor).strip())
    except ValueError:
        return None
