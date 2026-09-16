"""Consolidación de las extracciones por lead (TRD 8.4).

Un cliente puede tener varios leads y cada lead varias conversaciones. El puntaje trabaja sobre
el lead principal, así que aquí se reúnen las señales de todas las conversaciones del cliente
y se resumen en una sola fila: manda lo más reciente, salvo en lo que se acumula.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from pipeline.extract.schema import Extraccion, FormaPago, Intencion, MencionaCuota, Objecion
from pipeline.normalize import resolver_fecha

# Fecha imposible para ordenar de último lo que no tiene fecha legible.
_SIN_FECHA = "0001-01-01T00:00:00"


@dataclass(frozen=True)
class Senales:
    """Lo que el cliente dijo, visto desde el lead principal."""

    lead_id: str
    modelo_texto: str | None = None
    cuota_inicial_cop: int | None = None
    menciona_cuota: MencionaCuota = "NO_INFORMA"
    forma_pago: FormaPago = "no_informa"
    intencion: Intencion = "media"
    objecion: Objecion = "ninguna"
    pidio_cita: bool = False
    pidio_cotizacion: bool = False
    cliente_respondio: bool = False
    conversaciones: int = 0
    conversacion_ids: tuple[str, ...] = field(default_factory=tuple)


def _orden(conversacion: dict) -> tuple[str, str]:
    """Ordena por fecha de inicio; las ilegibles van primero para que no ganen la prioridad."""
    fecha = resolver_fecha(conversacion["fecha_inicio"], None, es_registro=False)[0]
    return (fecha.isoformat() if fecha else _SIN_FECHA, conversacion["conversacion_id"])


def _ultimo(valores: list, vacio) -> object:
    """El valor más reciente distinto del valor vacío; si no hay ninguno, el vacío."""
    return next((v for v in reversed(valores) if v != vacio and v is not None), vacio)


def consolidar(
    leads: pd.DataFrame,
    conversaciones: list[dict],
    extracciones: dict[str, Extraccion],
) -> dict[str, Senales]:
    """Señales por lead principal, reuniendo las conversaciones de todos los leads del cliente.

    Las conversaciones huérfanas no entran: no pertenecen a ningún lead ni a ninguna empresa.
    """
    # Cada lead pertenece a un cliente, identificado por (empresa_id, clave_dedup).
    cliente_de = {
        fila["lead_id"]: (fila["empresa_id"], fila["clave_dedup"])
        for fila in leads[["lead_id", "empresa_id", "clave_dedup"]].to_dict("records")
    }
    principal_de = {
        (fila["empresa_id"], fila["clave_dedup"]): fila["lead_id"]
        for fila in leads[leads["es_principal"]][["lead_id", "empresa_id", "clave_dedup"]].to_dict(
            "records"
        )
    }

    # Conversaciones de cada cliente, de la más antigua a la más reciente.
    por_cliente: dict[tuple, list[dict]] = {}
    for conversacion in conversaciones:
        cliente = cliente_de.get(conversacion["lead_id"])
        if cliente is None or conversacion["conversacion_id"] not in extracciones:
            continue  # huérfana, o sin extracción disponible
        por_cliente.setdefault(cliente, []).append(conversacion)

    senales = {}
    for cliente, sus_conversaciones in por_cliente.items():
        lead_id = principal_de.get(cliente)
        if lead_id is None:
            continue
        ordenadas = sorted(sus_conversaciones, key=_orden)
        senales[lead_id] = _resumir(lead_id, ordenadas, extracciones)
    return senales


def _resumir(lead_id: str, ordenadas: list[dict], extracciones: dict[str, Extraccion]) -> Senales:
    """Aplica las reglas de TRD 8.4 sobre las conversaciones ya ordenadas por fecha."""
    ext = [extracciones[c["conversacion_id"]] for c in ordenadas]

    # La cuota y su mención viajan juntas: se toma la última conversación que dio una cifra.
    con_cuota = [e for e in ext if e.cuota_inicial_cop is not None]
    if con_cuota:
        cuota = con_cuota[-1].cuota_inicial_cop
        menciona = con_cuota[-1].menciona_cuota
    else:
        cuota = None
        menciona = _ultimo([e.menciona_cuota for e in ext], "NO_INFORMA")

    return Senales(
        lead_id=lead_id,
        modelo_texto=_ultimo([e.modelo_texto for e in ext], None),
        cuota_inicial_cop=cuota,
        menciona_cuota=menciona,
        forma_pago=_ultimo([e.forma_pago for e in ext], "no_informa"),
        # La intención es del momento: vale la de la conversación más reciente.
        intencion=ext[-1].intencion,
        objecion=_ultimo([e.objecion for e in ext], "ninguna"),
        # Pedir cita o cotización no se deshace: basta con haberlo hecho una vez.
        pidio_cita=any(e.pidio_cita for e in ext),
        pidio_cotizacion=any(e.pidio_cotizacion for e in ext),
        cliente_respondio=any(e.cliente_respondio for e in ext),
        conversaciones=len(ext),
        conversacion_ids=tuple(c["conversacion_id"] for c in ordenadas),
    )
