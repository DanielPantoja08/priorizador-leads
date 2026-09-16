"""Pruebas de la consolidación por lead (TRD 8.4)."""

from __future__ import annotations

import pandas as pd

from pipeline.extract.consolidar import consolidar
from pipeline.extract.schema import Extraccion


def tabla_leads(*filas: tuple[str, str, str, bool]) -> pd.DataFrame:
    """(lead_id, empresa_id, clave_dedup, es_principal)."""
    return pd.DataFrame(
        [
            dict(zip(("lead_id", "empresa_id", "clave_dedup", "es_principal"), f, strict=True))
            for f in filas
        ],
        dtype="object",
    )


def conversacion(cid: str, lead_id: str, fecha: str) -> dict:
    return {"conversacion_id": cid, "lead_id": lead_id, "fecha_inicio": fecha, "mensajes": []}


def test_manda_la_conversacion_mas_reciente() -> None:
    leads = tabla_leads(("LEAD-1", "EMP-01", "tel:573001112233", True))
    convs = [
        conversacion("CONV-VIEJA", "LEAD-1", "2026-09-01 10:00:00"),
        conversacion("CONV-NUEVA", "LEAD-1", "2026-09-05 10:00:00"),
    ]
    ext = {
        "CONV-VIEJA": Extraccion(
            conversacion_id="CONV-VIEJA", modelo_texto="Bajaj Boxer 150", intencion="baja"
        ),
        "CONV-NUEVA": Extraccion(
            conversacion_id="CONV-NUEVA", modelo_texto="Honda CB 190R", intencion="alta"
        ),
    }
    senales = consolidar(leads, convs, ext)["LEAD-1"]
    assert senales.modelo_texto == "Honda CB 190R"
    assert senales.intencion == "alta"
    assert senales.conversaciones == 2


def test_cita_y_cotizacion_se_acumulan() -> None:
    leads = tabla_leads(("LEAD-1", "EMP-01", "tel:573001112233", True))
    convs = [
        conversacion("CONV-A", "LEAD-1", "2026-09-01 10:00:00"),
        conversacion("CONV-B", "LEAD-1", "2026-09-05 10:00:00"),
    ]
    ext = {
        "CONV-A": Extraccion(conversacion_id="CONV-A", pidio_cita=True),
        "CONV-B": Extraccion(conversacion_id="CONV-B", pidio_cotizacion=True),
    }
    senales = consolidar(leads, convs, ext)["LEAD-1"]
    assert senales.pidio_cita is True  # lo pidió en la vieja y no se pierde
    assert senales.pidio_cotizacion is True


def test_cuota_toma_el_ultimo_valor_no_nulo() -> None:
    leads = tabla_leads(("LEAD-1", "EMP-01", "tel:573001112233", True))
    convs = [
        conversacion("CONV-A", "LEAD-1", "2026-09-01 10:00:00"),
        conversacion("CONV-B", "LEAD-1", "2026-09-05 10:00:00"),
    ]
    ext = {
        "CONV-A": Extraccion(
            conversacion_id="CONV-A", cuota_inicial_cop=2_000_000, menciona_cuota="SI"
        ),
        "CONV-B": Extraccion(conversacion_id="CONV-B", cuota_inicial_cop=None),
    }
    senales = consolidar(leads, convs, ext)["LEAD-1"]
    assert senales.cuota_inicial_cop == 2_000_000
    assert senales.menciona_cuota == "SI"


def test_reune_los_leads_del_mismo_cliente_en_el_principal() -> None:
    # Dos leads del mismo cliente (misma clave), uno principal; cada uno con su conversación.
    leads = tabla_leads(
        ("LEAD-VIEJO", "EMP-01", "tel:573001112233", False),
        ("LEAD-NUEVO", "EMP-01", "tel:573001112233", True),
    )
    convs = [
        conversacion("CONV-A", "LEAD-VIEJO", "2026-09-01 10:00:00"),
        conversacion("CONV-B", "LEAD-NUEVO", "2026-09-05 10:00:00"),
    ]
    ext = {
        "CONV-A": Extraccion(conversacion_id="CONV-A", pidio_cita=True, forma_pago="contado"),
        "CONV-B": Extraccion(conversacion_id="CONV-B", intencion="media"),
    }
    senales = consolidar(leads, convs, ext)
    assert list(senales) == ["LEAD-NUEVO"]  # solo el principal recibe las señales
    assert senales["LEAD-NUEVO"].conversaciones == 2
    assert senales["LEAD-NUEVO"].pidio_cita is True
    assert senales["LEAD-NUEVO"].forma_pago == "contado"


def test_ignora_conversaciones_huerfanas() -> None:
    leads = tabla_leads(("LEAD-1", "EMP-01", "tel:573001112233", True))
    convs = [
        conversacion("CONV-A", "LEAD-1", "2026-09-01 10:00:00"),
        conversacion("CONV-HUERFANA", "LEAD-INEXISTENTE", "2026-09-02 10:00:00"),
    ]
    ext = {
        "CONV-A": Extraccion(conversacion_id="CONV-A"),
        "CONV-HUERFANA": Extraccion(conversacion_id="CONV-HUERFANA", pidio_cita=True),
    }
    senales = consolidar(leads, convs, ext)
    assert senales["LEAD-1"].conversaciones == 1
    assert senales["LEAD-1"].pidio_cita is False


def test_lead_sin_conversaciones_no_aparece() -> None:
    leads = tabla_leads(("LEAD-1", "EMP-01", "tel:573001112233", True))
    assert consolidar(leads, [], {}) == {}


def test_fecha_ilegible_no_gana_la_prioridad() -> None:
    leads = tabla_leads(("LEAD-1", "EMP-01", "tel:573001112233", True))
    convs = [
        conversacion("CONV-RARA", "LEAD-1", "fecha que no se entiende"),
        conversacion("CONV-BUENA", "LEAD-1", "2026-09-05 10:00:00"),
    ]
    ext = {
        "CONV-RARA": Extraccion(conversacion_id="CONV-RARA", intencion="baja"),
        "CONV-BUENA": Extraccion(conversacion_id="CONV-BUENA", intencion="alta"),
    }
    assert consolidar(leads, convs, ext)["LEAD-1"].intencion == "alta"
