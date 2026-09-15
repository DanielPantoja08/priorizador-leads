"""Perfil de los insumos y calidad de datos de los leads actuales (TRD 17, puntos 1, 2 y 3)."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta

import matplotlib.pyplot as plt
import pandas as pd
from rapidfuzz import fuzz

from eda.comun import (
    cargar_conversaciones,
    cargar_csv,
    clase_barras,
    clave_texto,
    forma_telefono,
    formato_fecha,
    guardar_figura,
    lecturas_fecha,
    miles,
    normalizar_telefono,
    pct,
    resolver_fecha,
    tabla_md,
)

# Mapeos canónicos de la sección 6 del TRD (claves sin tildes y en minúsculas).
CANALES = {"whatsapp": "WhatsApp", "meta ads": "Meta Ads", "formulario web": "Formulario Web"}
ESTADOS = {
    "sin gestion": "Sin gestión",
    "no contesta": "No contesta",
    "contactado": "Contactado",
    "en proceso": "En proceso",
    "cotizacion enviada": "Cotización enviada",
    "descartado": "Descartado",
}
# Sinónimos que el TRD cita de forma explícita.
CIUDADES_TRD = {
    "b/quilla": "Barranquilla",
    "sta marta": "Santa Marta",
    "rio negro": "Rionegro",
    "bogota dc": "Bogotá D.C.",
    "cartagena de indias": "Cartagena",
}
# Nombre oficial de cada ciudad, para lo que solo difiere en tildes o mayúsculas.
CIUDADES_OFICIALES = {
    "barranquilla": "Barranquilla",
    "santa marta": "Santa Marta",
    "rionegro": "Rionegro",
    "bogota d.c.": "Bogotá D.C.",
    "cartagena": "Cartagena",
    "medellin": "Medellín",
    "itagui": "Itagüí",
    "monteria": "Montería",
    "bello": "Bello",
    "soledad": "Soledad",
    "soacha": "Soacha",
}
UMBRAL_COMPLETO = 85
UMBRAL_LINEA = 90


# ---------------------------------------------------------------------------
# 1. Perfil de archivos
# ---------------------------------------------------------------------------
def perfil_csv(nombre: str, df: pd.DataFrame) -> str:
    """Tabla de perfil por columna: nulos, cardinalidad y valores (si hay 12 o menos)."""
    filas = []
    for columna in df.columns:
        serie = df[columna]
        distintos = serie.dropna().unique()
        if len(distintos) <= 12:
            conteo = serie.value_counts(dropna=True).sort_index()
            valores = "; ".join(f"`{v}` ({n})" for v, n in conteo.items())
        else:
            valores = "ej.: " + ", ".join(f"`{v}`" for v in sorted(distintos)[:3])
        filas.append([f"`{columna}`", int(serie.isna().sum()), len(distintos), valores])
    encabezado = f"#### `{nombre}` — {miles(len(df))} filas, {len(df.columns)} columnas\n\n"
    return encabezado + tabla_md(["Columna", "Nulos", "Distintos", "Valores"], filas)


def perfil_conversaciones(conversaciones: list[dict]) -> str:
    """Resumen estructural de conversaciones.json."""
    mensajes = [m for c in conversaciones for m in c["mensajes"]]
    emisores = Counter(m["emisor"] for m in mensajes)
    canales = Counter(c["canal"] for c in conversaciones)
    ids = Counter(c["conversacion_id"] for c in conversaciones)
    formatos = Counter(formato_fecha(c["fecha_inicio"]) for c in conversaciones)
    filas = [
        ["Conversaciones", miles(len(conversaciones))],
        ["`conversacion_id` repetidos", sum(1 for n in ids.values() if n > 1)],
        ["Claves por objeto", ", ".join(f"`{k}`" for k in conversaciones[0].keys())],
        ["Canal", "; ".join(f"`{k}` ({v})" for k, v in canales.items())],
        ["Formato de `fecha_inicio`", "; ".join(f"{k} ({v})" for k, v in formatos.items())],
        ["Mensajes", miles(len(mensajes))],
        ["Emisores", "; ".join(f"`{k}` ({v})" for k, v in sorted(emisores.items()))],
    ]
    return "#### `conversaciones.json`\n\n" + tabla_md(["Atributo", "Valor"], filas)


# ---------------------------------------------------------------------------
# Modelo de interés (TRD 6.2), solo para medir
# ---------------------------------------------------------------------------
def limpiar_modelo(texto) -> str | None:
    """Minúsculas, sin tildes, a.k.t -> akt, sin año y con espacios colapsados."""
    limpio = clave_texto(texto)
    if limpio is None:
        return None
    limpio = limpio.replace("a.k.t", "akt")
    limpio = re.sub(r"\b20\d{2}\b", "", limpio)
    return " ".join(limpio.split()) or None


def resolver_modelo(texto, catalogo: pd.DataFrame) -> tuple[str | None, str | None, str]:
    """Aplica la regla 6.2 y devuelve (sku, marca, regla)."""
    limpio = limpiar_modelo(texto)
    if limpio is None:
        return None, None, "modelo_faltante"

    completos = {
        fila.sku: fuzz.token_set_ratio(limpio, limpiar_modelo(f"{fila.marca} {fila.linea}"))
        for fila in catalogo.itertuples()
    }
    mejor = max(completos.values())
    empatados = [sku for sku, p in completos.items() if p == mejor]
    if mejor >= UMBRAL_COMPLETO and len(empatados) == 1:
        sku = empatados[0]
        return sku, catalogo.set_index("sku").at[sku, "marca"], "coincidencia_completa"

    por_linea = {
        fila.sku: fuzz.token_set_ratio(limpio, limpiar_modelo(fila.linea))
        for fila in catalogo.itertuples()
    }
    mejor_linea = max(por_linea.values())
    empatados_linea = [sku for sku, p in por_linea.items() if p == mejor_linea]
    if mejor_linea >= UMBRAL_LINEA and len(empatados_linea) == 1:
        sku = empatados_linea[0]
        return sku, catalogo.set_index("sku").at[sku, "marca"], "coincidencia_linea"

    for marca in catalogo["marca"].unique():
        if fuzz.partial_ratio(marca.lower(), limpio) >= UMBRAL_COMPLETO:
            return None, marca, "modelo_ambiguo"
    return None, None, "sin_coincidencia"


# ---------------------------------------------------------------------------
# Preparación de leads para medir
# ---------------------------------------------------------------------------
def preparar_leads(leads: pd.DataFrame, catalogo: pd.DataFrame) -> pd.DataFrame:
    """Agrega columnas normalizadas (sin modificar los insumos) para medir calidad y duplicados."""
    df = leads.copy()
    df["fila_repetida"] = df.duplicated("lead_id", keep="first")
    df["canal_n"] = df["canal"].map(lambda v: CANALES.get(clave_texto(v)))
    df["estado_n"] = df["estado_gestion"].map(lambda v: ESTADOS.get(clave_texto(v)))
    df["telefono_n"] = df["telefono"].map(normalizar_telefono)
    df["email_n"] = df["email"].map(lambda v: clave_texto(v))
    df["es_prueba"] = df["nombre_cliente"].str.lower().str.contains("prueba", na=False) | (
        df["telefono_n"].isna() & df["canal_n"].isna()
    )

    registros, motivos_registro, contactos, motivos_contacto = [], [], [], []
    for fila in df.itertuples():
        f, m = resolver_fecha(fila.fecha_registro, fila.fecha_primer_contacto, es_registro=True)
        registros.append(f)
        motivos_registro.append(m)
        f, m = resolver_fecha(fila.fecha_primer_contacto, fila.fecha_registro, es_registro=False)
        contactos.append(f)
        motivos_contacto.append(m)
    # dtype object: conserva None en lugar de NaT, así las comparaciones con `is None` son explícitas.
    df["registro"] = pd.Series(registros, index=df.index, dtype="object")
    df["motivo_registro"] = motivos_registro
    df["contacto"] = pd.Series(contactos, index=df.index, dtype="object")
    df["motivo_contacto"] = motivos_contacto
    df["precision_registro"] = df["fecha_registro"].map(lambda v: lecturas_fecha(v)[1])
    df["precision_contacto"] = df["fecha_primer_contacto"].map(lambda v: lecturas_fecha(v)[1])

    resueltos = df["modelo_interes_texto"].map(lambda v: resolver_modelo(v, catalogo))
    df["sku"] = resueltos.map(lambda r: r[0])
    df["marca_interes"] = resueltos.map(lambda r: r[1])
    df["regla_modelo"] = resueltos.map(lambda r: r[2])
    return df


def leads_unicos(df: pd.DataFrame) -> pd.DataFrame:
    """Leads sin filas repetidas ni registros de prueba: la base de todas las cifras de negocio."""
    return df[~df["fila_repetida"] & ~df["es_prueba"]].copy()


def _por_dia(fila) -> bool:
    return fila.precision_registro == "dia" or fila.precision_contacto == "dia"


# ---------------------------------------------------------------------------
# 2. Calidad de datos
# ---------------------------------------------------------------------------
def tabla_calidad(
    df: pd.DataFrame, catalogo: pd.DataFrame, asesores: pd.DataFrame
) -> tuple[str, dict]:
    """Tabla problema / casos / ejemplo / resolución y cifras de apoyo."""
    filas: list[list] = []
    cifras: dict = {}

    def agregar(problema, casos, ejemplo, resolucion, nueva=False):
        etiqueta = f"**{problema}** (nueva)" if nueva else problema
        filas.append([etiqueta, casos, ejemplo, resolucion])

    canal_no_canonico = df[df["canal"].notna() & (df["canal"] != df["canal_n"])]
    agregar(
        "Canal con mayúsculas o minúsculas no estándar",
        len(canal_no_canonico),
        f"`{canal_no_canonico['canal'].iloc[0]}`",
        "Mapeo a WhatsApp, Meta Ads o Formulario Web",
    )
    agregar(
        "Canal nulo",
        int(df["canal"].isna().sum()),
        "—",
        "Registro de prueba si además el teléfono es inválido",
    )

    estado_no_canonico = df[df["estado_gestion"] != df["estado_n"]]
    agregar(
        "Estado de gestión no estándar",
        len(estado_no_canonico),
        ", ".join(f"`{v}`" for v in sorted(estado_no_canonico["estado_gestion"].unique())),
        "Sin tildes y en minúsculas, luego catálogo de 6 estados",
    )

    formas = Counter(forma_telefono(t) for t in df["telefono"])
    agregar(
        "Teléfono en formatos distintos",
        f"{sum(n for f, n in formas.items() if f != '9999999999')} en {len(formas) - 1} formatos no estándar",
        ", ".join(f"`{f}` ({n})" for f, n in formas.most_common()),
        "Solo dígitos, sin prefijo 57, válido si tiene 10 dígitos y empieza por 3",
    )
    cifras["formatos_telefono"] = len(formas)
    invalidos = df[df["telefono_n"].isna()]
    agregar(
        "Teléfono inválido",
        len(invalidos),
        ", ".join(f"`{t}`" for t in invalidos["telefono"]),
        "Bandera `telefono_invalido`; clave secundaria por email",
    )

    agregar("Email nulo", int(df["email"].isna().sum()), "—", "Se conserva nulo")
    patron_email = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    emails = df["email"].dropna()
    agregar(
        "Email con formato inválido o sin normalizar",
        int(sum(1 for e in emails if not patron_email.match(e.strip()) or e != e.strip().lower())),
        "—",
        "`strip().lower()` y validación básica",
    )

    espacios = df[df["nombre_cliente"] != df["nombre_cliente"].str.strip()]
    agregar(
        "Nombre con espacios sobrantes",
        len(espacios),
        f"`'{espacios['nombre_cliente'].iloc[0]}'`",
        "Recorte de espacios",
    )
    nombres = df["nombre_cliente"].str.strip()
    capitalizacion = df[(nombres == nombres.str.upper()) | (nombres == nombres.str.lower())]
    agregar(
        "Nombre todo en mayúsculas o minúsculas",
        len(capitalizacion),
        f"`{capitalizacion['nombre_cliente'].str.strip().iloc[0]}`",
        "Formato título",
    )
    abreviados = df[df["nombre_cliente"].str.contains(r"\b[A-ZÁÉÍÓÚÑ]\.", regex=True, na=False)]
    agregar(
        "Nombre abreviado",
        len(abreviados),
        f"`{abreviados['nombre_cliente'].str.strip().iloc[0]}`",
        "Se conserva en el lead; el cliente toma el nombre más largo",
    )

    claves_ciudad = df["ciudad"].map(clave_texto)
    por_trd = claves_ciudad.isin(CIUDADES_TRD.keys())
    agregar(
        "Ciudad con sinónimo o abreviatura",
        int(por_trd.sum()),
        ", ".join(f"`{v}`" for v in sorted(df.loc[por_trd, "ciudad"].unique())),
        "Diccionario de sinónimos del TRD",
    )
    oficiales = claves_ciudad.map(lambda c: CIUDADES_OFICIALES.get(c) or CIUDADES_TRD.get(c))
    solo_forma = df["ciudad"].notna() & ~por_trd & (df["ciudad"] != oficiales)
    agregar(
        "Ciudad que solo difiere en tildes, mayúsculas o espacios",
        int(solo_forma.sum()),
        ", ".join(f"`{v}`" for v in sorted(df.loc[solo_forma, "ciudad"].unique())[:6]) + "…",
        "Sin tildes y en minúsculas, luego nombre oficial",
    )
    bogota = df[claves_ciudad.isin(["bogota", "bogota d.c."])]
    agregar(
        "`Bogotá` y `Bogotá D.C.` conviven y el TRD solo mapea `bogota dc`",
        len(bogota),
        ", ".join(f"`{v}`" for v in sorted(bogota["ciudad"].unique())),
        "`bogota`, `bogota d.c.` y `bogota dc` → Bogotá D.C. (TRD 1.2, sección 6)",
        nueva=True,
    )
    agregar("Ciudad nula", int(df["ciudad"].isna().sum()), "—", "Se conserva nula")
    no_mapeadas = sorted(
        {
            c
            for c in claves_ciudad.dropna()
            if c not in CIUDADES_OFICIALES and c not in CIUDADES_TRD and c != "bogota"
        }
    )
    cifras["ciudades_sin_mapeo"] = no_mapeadas

    prueba = df[df["es_prueba"]]
    agregar(
        "Registro de prueba",
        len(prueba),
        ", ".join(
            f"`{r.lead_id}` `{r.nombre_cliente}` tel `{r.telefono}`" for r in prueba.itertuples()
        ),
        "Se excluye",
    )
    repetidas = df[df["fila_repetida"]]
    identicas = all(
        (
            df[df["lead_id"] == lid]
            .drop(columns=[c for c in df.columns if c not in leads_columnas(df)])
            .nunique()
            <= 1
        ).all()
        for lid in repetidas["lead_id"]
    )
    agregar(
        "`lead_id` repetido",
        len(repetidas),
        ", ".join(f"`{v}`" for v in repetidas["lead_id"])
        + (" (filas idénticas)" if identicas else " (filas distintas)"),
        "Se conserva la primera y se registra `lead_repetido`",
    )

    # Fechas
    for campo, etiqueta in (("fecha_registro", "registro"), ("fecha_primer_contacto", "contacto")):
        formatos = Counter(df[campo].map(formato_fecha))
        agregar(
            f"Formatos de fecha de {etiqueta}",
            f"{len([f for f in formatos if f != 'vacio'])} formatos",
            "; ".join(f"{f} ({n})" for f, n in formatos.most_common()),
            "Regla 6.1 del TRD",
        )
    cifras["formatos_fecha"] = len(
        {
            formato_fecha(v)
            for campo in ("fecha_registro", "fecha_primer_contacto")
            for v in df[campo]
        }
        - {"vacio"}
    )

    barras = [
        v
        for campo in ("fecha_registro", "fecha_primer_contacto")
        for v in df[campo].dropna()
        if formato_fecha(v) == "barras"
    ]
    clases = Counter(clase_barras(v) for v in barras)
    agregar(
        "Fechas `NN/NN/YYYY HH:MM` (registro y contacto)",
        len(barras),
        f"dd/mm determinada {clases['ddmm']}; mm/dd determinada {clases['mmdd']}; día = mes {clases['igual']}; "
        f"ambiguas {clases['ambigua']}",
        "Componente > 12, ventana, coherencia y dd/mm por defecto",
    )
    cifras["clases_barras"] = dict(clases)
    motivos = Counter(df["motivo_registro"]) + Counter(df["motivo_contacto"])
    cifras["motivos_fecha"] = dict(motivos)
    invalidas = df[(df["motivo_registro"] == "invalida") | (df["motivo_contacto"] == "invalida")]
    agregar(
        "Fecha imposible",
        len(invalidas),
        ", ".join(
            f"`{r.lead_id}`: `{r.fecha_registro if r.motivo_registro == 'invalida' else r.fecha_primer_contacto}`"
            for r in invalidas.itertuples()
        )
        or "—",
        "Se guarda nula con `fecha_invalida`",
    )

    antes = [
        r.lead_id
        for r in df.itertuples()
        if r.registro is not None
        and r.contacto is not None
        and ((r.contacto.date() < r.registro.date()) if _por_dia(r) else (r.contacto < r.registro))
    ]
    agregar(
        "Contacto antes del registro",
        len(antes),
        ", ".join(f"`{v}`" for v in antes[:5]) or "—",
        "Bandera `contacto_antes_de_registro`",
    )
    sin_fecha = df[(df["estado_n"] != "Sin gestión") & (df["fecha_primer_contacto"].isna())]
    agregar(
        "Estado gestionado sin fecha de contacto",
        len(sin_fecha),
        ", ".join(f"`{v}`" for v in sorted(sin_fecha["estado_n"].dropna().unique())),
        "Bandera `estado_sin_fecha_contacto`",
    )
    con_fecha = df[(df["estado_n"] == "Sin gestión") & (df["fecha_primer_contacto"].notna())]
    agregar(
        "Estado `Sin gestión` con fecha de primer contacto",
        len(con_fecha),
        ", ".join(f"`{v}`" for v in con_fecha["lead_id"].head(3)) or "—",
        "Bandera `sin_gestion_con_contacto` (TRD 1.2, sección 6.1)",
        nueva=len(con_fecha) > 0,
    )

    # Modelo
    reglas = Counter(df["regla_modelo"])
    cifras["reglas_modelo"] = dict(reglas)
    variantes = df.groupby("regla_modelo")["modelo_interes_texto"].nunique()
    agregar(
        "Modelo de interés en texto libre",
        f"{df['modelo_interes_texto'].nunique()} variantes",
        "; ".join(
            f"{regla}: {reglas[regla]} leads / {variantes.get(regla, 0)} variantes"
            for regla in sorted(reglas)
        ),
        "Regla 6.2 (rapidfuzz 85 / 90)",
    )
    sin_match = df[df["regla_modelo"] == "sin_coincidencia"]["modelo_interes_texto"].unique()
    cifras["modelo_sin_coincidencia"] = sorted(sin_match)

    # Disponibilidad del modelo en el punto de venta del lead
    disponibles = {
        fila.sku: set(fila.puntos_venta_disponibles.split("|")) for fila in catalogo.itertuples()
    }
    no_disponible = df[
        df["sku"].notna()
        & df.apply(
            lambda r: (
                r["sku"] is not None and r["punto_venta_id"] not in disponibles.get(r["sku"], set())
            ),
            axis=1,
        )
    ]
    agregar(
        "Modelo pedido no disponible en el punto de venta del lead",
        len(no_disponible),
        f"`{no_disponible['lead_id'].iloc[0]}` pide `{no_disponible['sku'].iloc[0]}` en `{no_disponible['punto_venta_id'].iloc[0]}`"
        if len(no_disponible)
        else "—",
        "`modelo_disponible_pv`, informativo para el asesor; no suma puntos (TRD 1.2, sección 6.2)",
        nueva=len(no_disponible) > 0,
    )

    capacidad = "capacidad_diaria_leads" in asesores.columns
    agregar(
        "Nombre de columna de capacidad distinto al TRD",
        "1 columna" if capacidad else 0,
        "`capacidad_diaria_leads` en el CSV, `capacidad_diaria` en el modelo de datos",
        "Se renombra en la ingesta (TRD 1.2, secciones 5.1 y 6)",
        nueva=capacidad,
    )
    return tabla_md(["Problema", "Casos", "Ejemplo", "Resolución"], filas), cifras


def leads_columnas(df: pd.DataFrame) -> list[str]:
    """Columnas originales de leads.csv (sin las columnas de medición)."""
    return [
        "lead_id", "fecha_registro", "canal", "empresa_id", "punto_venta_id", "nombre_cliente",
        "telefono", "email", "ciudad", "modelo_interes_texto", "estado_gestion",
        "fecha_primer_contacto", "campania",
    ]  # fmt: skip


# ---------------------------------------------------------------------------
# Punto de venta, empresa y ciudad
# ---------------------------------------------------------------------------
def relacion_punto_venta(df: pd.DataFrame) -> str:
    """Empresa por punto de venta y ciudad más frecuente de sus leads."""
    filas = []
    ciudades = df["ciudad"].map(
        lambda c: (
            CIUDADES_OFICIALES.get(clave_texto(c))
            or CIUDADES_TRD.get(clave_texto(c))
            or ("Bogotá D.C." if clave_texto(c) == "bogota" else None)
        )
    )
    df = df.assign(ciudad_n=ciudades)
    for pv, grupo in df.groupby("punto_venta_id"):
        empresas = grupo["empresa_id"].unique()
        conteo = grupo["ciudad_n"].value_counts()
        principal = conteo.index[0] if len(conteo) else "—"
        participacion = conteo.iloc[0] / grupo["ciudad_n"].notna().sum() if len(conteo) else 0
        filas.append(
            [pv, ", ".join(empresas), len(grupo), principal, pct(participacion), len(conteo)]
        )
    return tabla_md(
        [
            "Punto de venta",
            "Empresa",
            "Leads",
            "Ciudad más frecuente",
            "% de leads con esa ciudad",
            "Ciudades distintas",
        ],
        filas,
    )


# ---------------------------------------------------------------------------
# 3. Duplicados, conversaciones y volumen
# ---------------------------------------------------------------------------
def contar_grupos(base: pd.DataFrame) -> int:
    """Grupos `(empresa_id, teléfono)` con más de un registro en la base dada."""
    tamanos = base[base["telefono_n"].notna()].groupby(["empresa_id", "telefono_n"]).size()
    return int((tamanos > 1).sum())


def duplicados(unicos: pd.DataFrame) -> tuple[str, dict]:
    """Teléfonos compartidos entre empresas y grupos duplicados dentro de la empresa (TRD 7)."""
    validos = unicos[unicos["telefono_n"].notna()]
    empresas_por_tel = validos.groupby("telefono_n")["empresa_id"].nunique()
    compartidos = int((empresas_por_tel > 1).sum())

    grupos = validos.groupby(["empresa_id", "telefono_n"])
    tamanos = grupos.size()
    duplicados_ = tamanos[tamanos > 1]
    canales = grupos["canal_n"].nunique()
    multicanal = int((canales[duplicados_.index] > 1).sum())
    leads_en_grupos = int(duplicados_.sum())

    # Similitud de nombres dentro de cada grupo (TRD 7, confirmación).
    colisiones = 0
    for clave in duplicados_.index:
        nombres = [clave_texto(n) for n in grupos.get_group(clave)["nombre_cliente"]]
        similitud = min(
            fuzz.token_set_ratio(a, b) for i, a in enumerate(nombres) for b in nombres[i + 1 :]
        )
        colisiones += similitud < 60

    # Clave secundaria: teléfono inválido pero email válido.
    sin_tel = unicos[unicos["telefono_n"].isna() & unicos["email_n"].notna()]
    por_email = unicos[unicos["email_n"].notna()].groupby(["empresa_id", "email_n"]).size()
    grupos_email = int((por_email > 1).sum())

    cifras = {
        "telefonos_compartidos": compartidos,
        "grupos_duplicados": len(duplicados_),
        "grupos_multicanal": multicanal,
        "leads_en_grupos": leads_en_grupos,
        "posibles_colisiones": int(colisiones),
        "sin_telefono_con_email": len(sin_tel),
        "grupos_email": grupos_email,
        "tamano_max_grupo": int(duplicados_.max()) if len(duplicados_) else 0,
    }
    filas = [
        ["Teléfonos válidos que aparecen en más de una empresa", compartidos],
        ["Grupos `(empresa_id, teléfono)` con más de un lead", len(duplicados_)],
        ["…de ellos con más de un canal (multicanal)", multicanal],
        ["Leads dentro de esos grupos", leads_en_grupos],
        ["Tamaño máximo de grupo", cifras["tamano_max_grupo"]],
        ["Grupos con similitud de nombre < 60 (`posible_colision_telefono`)", int(colisiones)],
        ["Leads con teléfono inválido y email válido (clave secundaria)", len(sin_tel)],
        ["Grupos `(empresa_id, email)` con más de un lead", grupos_email],
    ]
    return tabla_md(["Medida", "Valor"], filas), cifras


def relacion_conversaciones(unicos: pd.DataFrame, conversaciones: list[dict]) -> tuple[str, dict]:
    """Huérfanas, leads con varias conversaciones y coherencia de fechas con el lead."""
    ids = set(unicos["lead_id"])
    por_lead = Counter(c["lead_id"] for c in conversaciones)
    huerfanas = [c for c in conversaciones if c["lead_id"] not in ids]
    con_dos = sum(1 for lid, n in por_lead.items() if n == 2 and lid in ids)
    con_mas = sum(1 for lid, n in por_lead.items() if n > 2 and lid in ids)
    indice = unicos.set_index("lead_id")
    canal_lead = Counter(
        indice.at[c["lead_id"], "canal_n"] for c in conversaciones if c["lead_id"] in ids
    )
    leads_con_conv = sum(1 for lid in por_lead if lid in ids)

    antes = 0
    for c in conversaciones:
        if c["lead_id"] in ids:
            registro = indice.at[c["lead_id"], "registro"]
            inicio = lecturas_fecha(c["fecha_inicio"])[0][0][0]
            if registro is not None and inicio.date() < registro.date():
                antes += 1

    cifras = {
        "huerfanas": len(huerfanas),
        "leads_dos_conversaciones": con_dos,
        "leads_mas_de_dos": con_mas,
        "leads_con_conversacion": leads_con_conv,
        "conversacion_antes_registro": antes,
    }
    filas = [
        [
            "Conversaciones huérfanas (`lead_id` inexistente)",
            len(huerfanas),
            ", ".join(f"`{c['lead_id']}`" for c in huerfanas[:4]) + "…",
        ],
        ["Leads con exactamente dos conversaciones", con_dos, ""],
        ["Leads con más de dos conversaciones", con_mas, ""],
        ["Leads con al menos una conversación", leads_con_conv, pct(leads_con_conv / len(unicos))],
        [
            "Canal del lead dueño de la conversación",
            "",
            "; ".join(f"{k} ({v})" for k, v in canal_lead.most_common()),
        ],
        ["Conversaciones que empiezan un día antes del registro del lead", antes, ""],
    ]
    return tabla_md(["Medida", "Valor", "Detalle"], filas), cifras


def sin_contacto_24h(unicos: pd.DataFrame, momento_corte) -> tuple[str, dict]:
    """% de leads no contactados en 24 h o nunca, con el método explícito."""
    tarde, nunca, dudosos = 0, 0, 0
    for r in unicos.itertuples():
        if r.contacto is None:
            nunca += 1
        elif _por_dia(r):
            dias = (r.contacto.date() - r.registro.date()).days
            if dias > 1:
                tarde += 1
            elif dias == 1:
                dudosos += 1  # con precisión de día no se sabe si pasaron más de 24 h
        elif (r.contacto - r.registro).total_seconds() > 24 * 3600:
            tarde += 1
    total = len(unicos)
    base = (tarde + nunca) / total
    # Variante "medianoche": las fechas con precisión de día se leen como 00:00 y se comparan en horas.
    medianoche = (
        sum(
            1
            for r in unicos.itertuples()
            if r.contacto is None or (r.contacto - r.registro).total_seconds() > 86400
        )
        / total
    )
    pesimista = (tarde + nunca + dudosos) / total

    maduros = unicos[
        unicos["registro"].map(lambda f: f is not None and f <= momento_corte - timedelta(hours=24))
    ]
    maduros_sin = sum(
        1
        for r in maduros.itertuples()
        if r.contacto is None
        or (
            (r.contacto.date() - r.registro.date()).days > 1
            if _por_dia(r)
            else (r.contacto - r.registro).total_seconds() > 86400
        )
    )
    cifras = {
        "sin_contacto_24h_medianoche": medianoche,
        "sin_contacto_24h": base,
        "sin_contacto_24h_pesimista": pesimista,
        "sin_contacto_24h_maduros": maduros_sin / len(maduros),
        "nunca": nunca / total,
    }
    filas = [
        ["Leads únicos (sin repetidos ni prueba)", miles(total)],
        ["Nunca contactados", f"{nunca} ({pct(nunca / total)})"],
        ["Contactados después de 24 h", f"{tarde} ({pct(tarde / total)})"],
        ["Precisión de día con 1 día de diferencia (no se puede saber)", dudosos],
        ["**Sin contacto en 24 h o nunca** (dudosos cuentan como a tiempo)", pct(base)],
        ["Igual, contando los dudosos como tarde", pct(pesimista)],
        [
            "Variante medianoche: fechas de día leídas como 00:00 y diferencia > 24 h",
            pct(medianoche),
        ],
        [
            "Solo leads con al menos 24 h de antigüedad al corte",
            f"{pct(maduros_sin / len(maduros))} de {miles(len(maduros))}",
        ],
    ]
    return tabla_md(["Medida", "Valor"], filas), cifras


def volumen_vs_capacidad(unicos: pd.DataFrame, asesores: pd.DataFrame) -> tuple[str, str, dict]:
    """Leads por día frente a la capacidad diaria de los asesores activos, por empresa."""
    activos = asesores[asesores["activo"] == "SI"].copy()
    activos["capacidad"] = activos["capacidad_diaria_leads"].astype(int)
    capacidad = activos.groupby("empresa_id")["capacidad"].sum()
    datos = unicos[unicos["registro"].notna()].assign(
        dia=lambda d: d["registro"].map(lambda f: f.date())
    )
    diario = datos.groupby(["empresa_id", "dia"]).size().unstack(0).fillna(0)
    todos = pd.date_range(min(datos["dia"]), max(datos["dia"])).date
    diario = diario.reindex(todos, fill_value=0)

    filas, cifras = [], {}
    for empresa in sorted(diario.columns):
        serie = diario[empresa]
        cap = int(capacidad.get(empresa, 0))
        abiertos = unicos[(unicos["empresa_id"] == empresa) & (unicos["estado_n"] != "Descartado")]
        filas.append([
            empresa, int(activos[activos["empresa_id"] == empresa].shape[0]), cap,
            f"{serie.mean():.1f}".replace(".", ","), int(serie.median()), int(serie.max()),
            pct(serie.mean() / cap) if cap else "—", miles(len(abiertos)),
        ])  # fmt: skip
        cifras[empresa] = {
            "capacidad": cap,
            "promedio": float(serie.mean()),
            "maximo": int(serie.max()),
            "abiertos": len(abiertos),
        }
    tabla = tabla_md(
        [
            "Empresa",
            "Asesores activos",
            "Capacidad diaria",
            "Leads/día (media)",
            "Mediana",
            "Máximo",
            "Uso medio de capacidad",
            "Leads abiertos (no descartados)",
        ],
        filas,
    )

    fig, eje = plt.subplots(figsize=(9, 3.8))
    for empresa in sorted(diario.columns):
        eje.plot(
            list(diario.index),
            diario[empresa],
            label=f"{empresa} (capacidad {cifras[empresa]['capacidad']})",
        )
    eje.set_title("Leads registrados por día y empresa")
    eje.set_ylabel("Leads")
    eje.legend()
    eje.grid(alpha=0.3)
    fig.autofmt_xdate()
    ruta = guardar_figura(fig, "volumen_diario.png")
    cifras["rango"] = (min(datos["dia"]), max(datos["dia"]))
    return tabla, ruta, cifras


def figura_formatos_fecha(df: pd.DataFrame) -> str:
    """Barras con los formatos de fecha por campo."""
    campos = {"fecha_registro": "Registro", "fecha_primer_contacto": "Primer contacto"}
    formatos = ["iso_espacio", "iso_t", "dd-mm-yyyy", "barras", "vacio"]
    fig, eje = plt.subplots(figsize=(8, 3.5))
    ancho = 0.4
    for i, (campo, etiqueta) in enumerate(campos.items()):
        conteo = Counter(df[campo].map(formato_fecha))
        eje.bar(
            [x + i * ancho for x in range(len(formatos))],
            [conteo.get(f, 0) for f in formatos],
            ancho,
            label=etiqueta,
        )
    eje.set_xticks([x + ancho / 2 for x in range(len(formatos))], formatos)
    eje.set_title("Formatos de fecha en leads.csv")
    eje.legend()
    return guardar_figura(fig, "formatos_fecha.png")


# ---------------------------------------------------------------------------
# Punto de entrada del módulo
# ---------------------------------------------------------------------------
def analizar() -> dict:
    """Ejecuta el perfil y la calidad; devuelve secciones Markdown y cifras para la verificación."""
    leads = cargar_csv("leads.csv")
    catalogo = cargar_csv("catalogo_motos.csv")
    asesores = cargar_csv("asesores.csv")
    historico = cargar_csv("historico_cierres.csv")
    conversaciones = cargar_conversaciones()

    df = preparar_leads(leads, catalogo)
    unicos = leads_unicos(df)
    registros = [f for f in unicos["registro"] if f is not None]
    momento_corte = max(registros)

    perfil = "\n\n".join(
        [
            perfil_csv("leads.csv", leads),
            perfil_csv("catalogo_motos.csv", catalogo),
            perfil_csv("asesores.csv", asesores),
            perfil_csv("historico_cierres.csv", historico),
            perfil_conversaciones(conversaciones),
        ]
    )
    calidad, cifras_calidad = tabla_calidad(df, catalogo, asesores)
    tabla_dup, cifras_dup = duplicados(unicos)
    tabla_conv, cifras_conv = relacion_conversaciones(unicos, conversaciones)
    tabla_24h, cifras_24h = sin_contacto_24h(unicos, momento_corte)
    tabla_volumen, figura_volumen, cifras_volumen = volumen_vs_capacidad(unicos, asesores)

    return {
        "perfil": perfil,
        "calidad": calidad,
        "figura_fechas": figura_formatos_fecha(df),
        "punto_venta": relacion_punto_venta(unicos),
        "duplicados": tabla_dup,
        "conversaciones": tabla_conv,
        "contacto_24h": tabla_24h,
        "volumen": tabla_volumen,
        "figura_volumen": figura_volumen,
        "cifras": {
            "filas_leads": len(leads),
            "conversaciones": len(conversaciones),
            "catalogo": len(catalogo),
            "asesores": len(asesores),
            "inactivos": sorted(asesores.loc[asesores["activo"] != "SI", "asesor_id"]),
            "historico": len(historico),
            "leads_unicos": len(unicos),
            "momento_corte": momento_corte,
            "puntos_venta_por_empresa": leads.groupby("empresa_id")["punto_venta_id"]
            .nunique()
            .to_dict(),
            "lineas_pulsar": int(catalogo["linea"].str.startswith("Pulsar").sum()),
            **cifras_calidad,
            **cifras_dup,
            # Mismo conteo sin quitar antes las filas con lead_id repetido (explica diferencias con el PRD).
            "grupos_con_repetidas": contar_grupos(df[~df["es_prueba"]]),
            **cifras_conv,
            **cifras_24h,
            "volumen": cifras_volumen,
        },
        "unicos": unicos,
        "catalogo": catalogo,
    }


if __name__ == "__main__":  # diagnóstico rápido: uv run python -m eda.perfil
    resultado = analizar()
    for clave, valor in resultado["cifras"].items():
        print(f"{clave}: {valor}")
    _ = date  # evita advertencias si se elimina el uso de date
