"""Pruebas del puntaje v2 (TRD 9): los tres componentes, la elegibilidad y el orden."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from pipeline.extract.consolidar import Senales
from pipeline.scoring import calcular, elegibles, momento_corte, temperatura_de

CORTE = datetime(2026, 9, 10, 12, 0)
PRECIOS = {"SKU-CARA": 12_000_000, "SKU-BARATA": 6_000_000}


def lead(lead_id: str, **cambios) -> dict:
    """Un lead elegible por defecto: principal, sin gestión y registrado el día del corte."""
    fila = {
        "lead_id": lead_id,
        "empresa_id": "EMP-01",
        "punto_venta_id": "PV-001",
        "canal": "WhatsApp",
        "clave_dedup": f"tel:{lead_id}",
        "fecha_registro": CORTE,
        "estado_gestion": "Sin gestión",
        "sku_interes": "SKU-BARATA",
        "es_principal": True,
    }
    return fila | cambios


def senales(lead_id: str = "LEAD-1", **cambios) -> dict[str, Senales]:
    return {lead_id: Senales(lead_id=lead_id, **cambios)}


def puntuar(filas: list[dict], sus_senales: dict | None = None, ventana: int = 30) -> list:
    df = pd.DataFrame(filas, dtype="object")
    return calcular(df, sus_senales or {}, PRECIOS, CORTE, ventana)


# --- Componente A: los pesos que respalda el histórico -------------------------------------


def test_calidad_suma_los_cuatro_factores() -> None:
    p = puntuar(
        [lead("LEAD-1", sku_interes="SKU-CARA")],
        senales(
            pidio_cita=True, menciona_cuota="SI", cuota_inicial_cop=2_000_000, forma_pago="contado"
        ),
    )[0]
    assert p.puntos_calidad == 9  # 3 cita + 3 cuota + 2 precio + 1 contado


def test_lead_sin_conversacion_suma_el_valor_esperado_y_queda_sin_calificar() -> None:
    # v2: sin chat no se sabe si pidió cita, tiene cuota o paga de contado. Eso no es un «no»:
    # suma el valor esperado de las tres señales (2) y el precio, y no se le pone temperatura.
    p = puntuar([lead("LEAD-1", sku_interes="SKU-CARA")])[0]
    assert p.puntos_calidad == 4  # 2 valor esperado + 2 precio
    assert p.temperatura == "Sin calificar"
    assert any("valor esperado" in r["factor"] for r in p.razones)


def test_sin_conversacion_no_queda_por_debajo_de_un_chat_sin_senales() -> None:
    # De quien escribió sin dar señales se sabe que no las dio; de quien no escribió, solo el
    # promedio del histórico.
    filas = [lead("LEAD-1"), lead("LEAD-2")]
    orden = puntuar(filas, senales("LEAD-1", cliente_respondio=True))
    assert [p.lead_id for p in orden] == ["LEAD-2", "LEAD-1"]
    assert orden[1].temperatura == "Frío"


def test_cuota_declarada_pero_sin_cifra_no_suma() -> None:
    p = puntuar([lead("LEAD-1")], senales(menciona_cuota="NO"))[0]
    assert p.puntos_calidad == 0


# --- Componente B: heurístico, recortado a ±3 -----------------------------------------------


@pytest.mark.parametrize(("intencion", "esperado"), [("alta", 2), ("media", 0), ("baja", -2)])
def test_intencion_ajusta(intencion: str, esperado: int) -> None:
    p = puntuar([lead("LEAD-1")], senales(intencion=intencion, cliente_respondio=True))[0]
    assert p.puntos_conversacion == esperado


def test_ajuste_se_recorta_al_rango() -> None:
    # −2 intención baja, −1 objeción bloqueante y −1 sin respuesta suman −4: se recorta a −3.
    p = puntuar(
        [lead("LEAD-1")],
        senales(intencion="baja", objecion="reporte_centrales", cliente_respondio=False),
    )[0]
    assert p.puntos_conversacion == -3
    assert any("recortado" in r["factor"] for r in p.razones)


def test_escribir_por_varios_canales_suma() -> None:
    # Dos leads del mismo cliente (misma clave) llegados por canales distintos.
    filas = [
        lead("LEAD-1", clave_dedup="tel:3001", canal="WhatsApp"),
        lead("LEAD-2", clave_dedup="tel:3001", canal="Meta Ads", es_principal=False),
    ]
    p = puntuar(filas, senales(cliente_respondio=True))[0]
    assert p.puntos_conversacion == 1


# --- Componente C: urgencia ------------------------------------------------------------------


@pytest.mark.parametrize(("horas", "esperado"), [(1, 5), (10, 4), (48, 2), (100, 1)])
def test_urgencia_sin_contacto_por_horas(horas: int, esperado: int) -> None:
    registro = CORTE - timedelta(hours=horas)
    p = puntuar([lead("LEAD-1", fecha_registro=registro)])[0]
    assert p.puntos_urgencia == esperado


@pytest.mark.parametrize(
    ("estado", "esperado"),
    [("Cotización enviada", 3), ("En proceso", 2), ("No contesta", 2), ("Contactado", 1)],
)
def test_urgencia_por_estado_manda_sobre_la_espera(estado: str, esperado: int) -> None:
    # Aunque el lead sea antiguo y no tenga fecha de contacto, su estado dice que sí se gestionó.
    antiguo = CORTE - timedelta(days=20)
    p = puntuar([lead("LEAD-1", estado_gestion=estado, fecha_registro=antiguo)])[0]
    assert p.puntos_urgencia == esperado


# --- Temperatura, prioritario y orden --------------------------------------------------------


@pytest.mark.parametrize(
    ("puntos", "esperado"),
    [(-3, "Frío"), (2, "Frío"), (3, "Tibio"), (5, "Tibio"), (6, "Caliente"), (9, "Caliente")],
)
def test_cortes_de_temperatura(puntos: int, esperado: str) -> None:
    assert temperatura_de(puntos) == esperado


def test_temperatura_no_incluye_la_urgencia() -> None:
    # Un lead recién registrado suma 5 de urgencia, pero eso no lo vuelve Caliente (TRD 9.2).
    p = puntuar([lead("LEAD-1")], senales(cliente_respondio=True))[0]
    assert p.puntos_urgencia == 5
    assert p.prioridad == 5
    assert p.temperatura == "Frío"


def test_prioritario_por_urgencia_aunque_sea_frio() -> None:
    p = puntuar([lead("LEAD-1")], senales(cliente_respondio=True))[0]
    assert p.temperatura == "Frío"
    assert p.prioritario is True  # sin contacto y con menos de 24 h


def test_lead_antiguo_sin_contacto_no_es_prioritario() -> None:
    antiguo = CORTE - timedelta(days=10)
    p = puntuar([lead("LEAD-1", fecha_registro=antiguo)])[0]
    assert p.prioritario is False


def test_orden_por_prioridad_y_luego_por_antiguedad() -> None:
    antiguo = CORTE - timedelta(hours=1)
    reciente = CORTE - timedelta(minutes=30)
    filas = [
        lead("LEAD-RECIENTE", clave_dedup="tel:1", fecha_registro=reciente),
        lead("LEAD-ANTIGUO", clave_dedup="tel:2", fecha_registro=antiguo),
    ]
    orden = [p.lead_id for p in puntuar(filas)]
    assert orden == ["LEAD-ANTIGUO", "LEAD-RECIENTE"]  # mismo puntaje, gana el más antiguo


# --- Elegibilidad ----------------------------------------------------------------------------


def test_descartados_y_secundarios_no_entran() -> None:
    filas = [
        lead("LEAD-OK", clave_dedup="tel:1"),
        lead("LEAD-DESCARTADO", clave_dedup="tel:2", estado_gestion="Descartado"),
        lead("LEAD-SECUNDARIO", clave_dedup="tel:3", es_principal=False),
    ]
    assert [p.lead_id for p in puntuar(filas)] == ["LEAD-OK"]


def test_fuera_de_la_ventana_no_entra() -> None:
    viejo = CORTE - timedelta(days=45)
    filas = [
        lead("LEAD-OK", clave_dedup="tel:1"),
        lead("LEAD-VIEJO", clave_dedup="tel:2", fecha_registro=viejo),
    ]
    assert [p.lead_id for p in puntuar(filas, ventana=30)] == ["LEAD-OK"]


def test_elegibles_devuelve_un_subconjunto_del_dataframe() -> None:
    df = pd.DataFrame([lead("LEAD-1"), lead("LEAD-2", clave_dedup="tel:2")], dtype="object")
    assert len(elegibles(df, CORTE, 30)) == 2


# --- Momento de corte -------------------------------------------------------------------------


def test_momento_corte_es_el_ultimo_registro_del_dia() -> None:
    ultimo = datetime(2026, 9, 10, 10, 50)
    df = pd.DataFrame(
        [
            lead("LEAD-1", fecha_registro=datetime(2026, 9, 1)),
            lead("LEAD-2", fecha_registro=ultimo),
        ],
        dtype="object",
    )
    assert momento_corte(df, ultimo.date()) == ultimo


def test_momento_corte_ignora_registros_posteriores_al_corte() -> None:
    # Si un insumo trae fechas futuras, no deben mover el momento contra el que se mide la espera.
    df = pd.DataFrame(
        [
            lead("LEAD-1", fecha_registro=datetime(2026, 9, 1, 8, 0)),
            lead("LEAD-FUTURO", fecha_registro=datetime(2026, 9, 20, 8, 0)),
        ],
        dtype="object",
    )
    assert momento_corte(df, datetime(2026, 9, 1).date()) == datetime(2026, 9, 1, 8, 0)


def test_ningun_lead_tiene_horas_negativas() -> None:
    # El corte nunca queda antes del registro, así que la urgencia no se dispara por el signo.
    df = pd.DataFrame([lead("LEAD-1")], dtype="object")
    corte = momento_corte(df, CORTE.date())
    assert corte >= CORTE
