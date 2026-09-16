"""Puntaje de prioridad y temperatura de cada lead (RF-06, RF-07, TRD 9).

El puntaje es aditivo y explicable: cada factor que suma o resta queda en `razones`, para que la
app pueda decirle al asesor por qué un lead está donde está. Son tres componentes:

- **A, calidad validada (0 a 9).** Sus pesos salen de las tasas de cierre del histórico (TRD 9.2).
  `eda/historico.py` y `evaluation/validate_scoring.py` usan estos mismos pesos: son la única
  fuente de esos números.
- **B, ajuste conversacional (−3 a +3).** Heurístico: el histórico no tiene estas señales.
- **C, urgencia (0 a 5).** Se apoya en la relación entre horas al primer contacto y cierre.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from pipeline.extract.consolidar import Senales

# Subir cualquier peso obliga a subir esta versión: la tabla `score` guarda una fila por versión.
VERSION_SCORE = "v1"

# Componente A (TRD 9.2). Las tasas que los justifican están en docs/EDA.md, sección 4.
PESOS_CALIDAD = {
    "cita": 3,  # pidió cita: cierra 11,8 % contra 8,9 %
    "cuota": 3,  # manifestó cuota inicial: 11,8 % contra 8,3 %
    "precio_alto": 2,  # modelo de $10 M o más: 11,5 % contra 8,5 %
    "contado": 1,  # pago de contado: 11,8 % contra 8,4 %
}
PRECIO_ALTO = 10_000_000

# Componente B. Pesos pequeños a propósito: no tienen respaldo histórico y la app los marca así.
PESOS_CONVERSACION = {
    "intencion_alta": 2,
    "intencion_baja": -2,
    "objecion_bloqueante": -1,  # reporte en centrales o sin con qué dar la inicial
    "no_respondio": -1,
    "multicanal": 1,  # el cliente escribió por más de un canal
}
LIMITE_CONVERSACION = 3  # el componente B se recorta a [−3, +3]
OBJECIONES_BLOQUEANTES = ("reporte_centrales", "sin_inicial")

# Componente C. Solo los leads sin gestión puntúan por horas; el resto, por su estado.
# Un lead con estado avanzado y sin fecha de contacto sí fue contactado: lo que falta es el dato,
# y por eso ya lleva la bandera `estado_sin_fecha_contacto` (decisión del punto de control C).
ESTADO_SIN_GESTION = "Sin gestión"
URGENCIA_SIN_CONTACTO = ((2, 5), (24, 4), (72, 2))  # (horas máximas, puntos); más allá, 1 punto
URGENCIA_TARDIA = 1
URGENCIA_POR_ESTADO = {
    "Cotización enviada": 3,  # seguimiento de cierre
    "En proceso": 2,
    "No contesta": 2,
    "Contactado": 1,
}

# Temperatura a partir de calidad + ajuste (TRD 9.2).
UMBRAL_CALIENTE = 6
UMBRAL_TIBIO = 3

# Validación temporal del puntaje (TRD 9.3): se entrena antes de esta fecha y se evalúa desde ella.
CORTE_TEMPORAL = date(2026, 6, 15)
# La tasa de cierre de los Caliente debe superar a la de los Frío por este factor en la prueba.
RAZON_MINIMA_CALIENTE_FRIO = 1.8

HORAS_URGENTE = 24  # marca de urgencia de HU-03, también usada para `prioritario`
ESTADO_EXCLUIDO = "Descartado"


@dataclass(frozen=True)
class Puntaje:
    """Puntaje de un lead para una fecha de corte, con las razones que lo componen."""

    lead_id: str
    empresa_id: str
    punto_venta_id: str
    puntos_calidad: int
    puntos_conversacion: int
    puntos_urgencia: int
    prioridad: int
    temperatura: str
    razones: list[dict]
    fecha_registro: datetime | None
    # Sin gestión y con menos de 24 h desde el registro: la marca de urgencia de HU-03.
    sin_contacto_reciente: bool

    @property
    def prioritario(self) -> bool:
        """Caliente, o sin contacto con menos de 24 h (TRD 10). No cambia la asignación."""
        return self.temperatura == "Caliente" or self.sin_contacto_reciente


def temperatura_de(puntos: int) -> str:
    """Caliente si es 6 o más, Tibio entre 3 y 5, Frío si es 2 o menos."""
    if puntos >= UMBRAL_CALIENTE:
        return "Caliente"
    return "Tibio" if puntos >= UMBRAL_TIBIO else "Frío"


def momento_corte(leads: pd.DataFrame, fecha_corte) -> datetime:
    """Momento contra el que se miden las horas de urgencia (TRD 9.2).

    Es el registro más reciente que no pase del final del día de corte. Usar la medianoche del
    parámetro daría horas negativas a los leads de ese mismo día; usar el reloj real haría que el
    puntaje cambiara entre corridas y rompería la idempotencia (RNF-03).
    """
    registros = [f for f in leads["fecha_registro"] if f is not None]
    # Los leads normalizados vienen en hora de Colombia; la zona se toma de los propios datos
    # para no comparar fechas con zona contra fechas sin ella.
    zona = next((f.tzinfo for f in registros), None)
    fin = datetime.combine(fecha_corte, datetime.max.time(), tzinfo=zona)
    dentro = [f for f in registros if f <= fin]
    return max(dentro) if dentro else fin


def _calidad(senales: Senales | None, precio_lista: int | None) -> tuple[int, list[dict]]:
    """Componente A: lo que el histórico respalda."""
    razones: list[dict] = []
    if senales is not None and senales.pidio_cita:
        razones.append({"factor": "pidió cita", "puntos": PESOS_CALIDAD["cita"]})
    if senales is not None and senales.menciona_cuota == "SI":
        razones.append({
            "factor": "manifestó cuota inicial",
            "puntos": PESOS_CALIDAD["cuota"],
            "valor": senales.cuota_inicial_cop,
        })  # fmt: skip
    if precio_lista is not None and precio_lista >= PRECIO_ALTO:
        razones.append({
            "factor": "modelo de gama alta",
            "puntos": PESOS_CALIDAD["precio_alto"],
            "valor": precio_lista,
        })  # fmt: skip
    if senales is not None and senales.forma_pago == "contado":
        razones.append({"factor": "paga de contado", "puntos": PESOS_CALIDAD["contado"]})
    return sum(r["puntos"] for r in razones), razones


def _conversacion(senales: Senales | None, canales: int) -> tuple[int, list[dict]]:
    """Componente B: lo que el cliente dijo. Se recorta a [−3, +3]."""
    razones: list[dict] = []
    if senales is not None:
        if senales.intencion == "alta":
            razones.append({
                "factor": "intención alta",
                "puntos": PESOS_CONVERSACION["intencion_alta"],
            })  # fmt: skip
        elif senales.intencion == "baja":
            razones.append({
                "factor": "intención baja",
                "puntos": PESOS_CONVERSACION["intencion_baja"],
            })  # fmt: skip
        if senales.objecion in OBJECIONES_BLOQUEANTES:
            razones.append({
                "factor": f"objeción: {senales.objecion}",
                "puntos": PESOS_CONVERSACION["objecion_bloqueante"],
            })  # fmt: skip
        if not senales.cliente_respondio:
            razones.append({
                "factor": "el cliente no respondió",
                "puntos": PESOS_CONVERSACION["no_respondio"],
            })  # fmt: skip
    if canales > 1:
        razones.append({
            "factor": "escribió por varios canales",
            "puntos": PESOS_CONVERSACION["multicanal"],
            "valor": canales,
        })  # fmt: skip

    bruto = sum(r["puntos"] for r in razones)
    recortado = max(-LIMITE_CONVERSACION, min(LIMITE_CONVERSACION, bruto))
    if recortado != bruto:
        razones.append({"factor": "ajuste recortado al rango ±3", "puntos": recortado - bruto})
    return recortado, razones


def _urgencia(estado: str, horas: float | None) -> tuple[int, list[dict], bool]:
    """Componente C. Devuelve (puntos, razones, sin contacto con menos de 24 h)."""
    if estado != ESTADO_SIN_GESTION:
        puntos = URGENCIA_POR_ESTADO.get(estado, URGENCIA_TARDIA)
        return puntos, [{"factor": f"estado: {estado}", "puntos": puntos}], False

    if horas is None:  # sin gestión y sin fecha de registro legible: no se puede medir la espera
        return (
            URGENCIA_TARDIA,
            [{"factor": "sin contacto, sin fecha", "puntos": URGENCIA_TARDIA}],
            False,
        )

    puntos = next((p for limite, p in URGENCIA_SIN_CONTACTO if horas < limite), URGENCIA_TARDIA)
    razon = {"factor": "sin contacto", "puntos": puntos, "valor": round(horas, 1)}
    return puntos, [razon], horas < HORAS_URGENTE


def elegibles(leads: pd.DataFrame, corte: datetime, ventana_dias: int) -> pd.DataFrame:
    """Leads principales, no descartados y registrados dentro de la ventana (TRD 9.2)."""
    desde = corte - timedelta(days=ventana_dias)
    dentro = [f is not None and desde <= f <= corte for f in leads["fecha_registro"]]
    return leads[
        leads["es_principal"]
        & leads["estado_gestion"].ne(ESTADO_EXCLUIDO)
        & pd.Series(dentro, index=leads.index)
    ]


def calcular(
    leads: pd.DataFrame,
    senales: dict[str, Senales],
    precios: dict[str, int],
    corte: datetime,
    ventana_dias: int,
) -> list[Puntaje]:
    """Puntaje de cada lead elegible, ordenado por prioridad descendente y registro ascendente."""
    # Canales distintos por cliente: un mismo cliente puede haber escrito por WhatsApp y por Meta.
    canales_por_cliente = leads.groupby(["empresa_id", "clave_dedup"])["canal"].nunique().to_dict()

    puntajes = []
    for fila in elegibles(leads, corte, ventana_dias).to_dict("records"):
        lead_id = fila["lead_id"]
        suyas = senales.get(lead_id)
        horas = None
        if fila["fecha_registro"] is not None:
            horas = (corte - fila["fecha_registro"]).total_seconds() / 3600

        calidad, razones_a = _calidad(suyas, precios.get(fila["sku_interes"]))
        ajuste, razones_b = _conversacion(
            suyas, canales_por_cliente.get((fila["empresa_id"], fila["clave_dedup"]), 1)
        )
        urgencia, razones_c, reciente = _urgencia(fila["estado_gestion"], horas)

        puntajes.append(
            Puntaje(
                lead_id=lead_id,
                empresa_id=fila["empresa_id"],
                punto_venta_id=fila["punto_venta_id"],
                puntos_calidad=calidad,
                puntos_conversacion=ajuste,
                puntos_urgencia=urgencia,
                prioridad=calidad + ajuste + urgencia,
                temperatura=temperatura_de(calidad + ajuste),
                razones=razones_a + razones_b + razones_c,
                fecha_registro=fila["fecha_registro"],
                sin_contacto_reciente=reciente,
            )
        )
    return ordenar(puntajes)


def ordenar(puntajes: list[Puntaje]) -> list[Puntaje]:
    """Prioridad descendente; ante empate, primero el lead más antiguo (HU-01)."""
    sin_fecha = datetime.max
    return sorted(
        puntajes,
        key=lambda p: (-p.prioridad, p.fecha_registro or sin_fecha, p.lead_id),
    )
