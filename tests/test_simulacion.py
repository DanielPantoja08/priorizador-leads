"""Pruebas de la simulación de políticas de atención (TRD 9.3)."""

from __future__ import annotations

import pandas as pd
import pytest

from evaluation.simular_politica import (
    cierres_al_azar,
    cierres_capturados,
    comparar,
    cupo,
    dias_de,
    por_llegada,
    por_puntaje,
    tabla,
)


def dia(*leads: tuple[str, int, int], fecha: str = "2026-03-01") -> pd.DataFrame:
    """Una jornada: (lead_id, puntos, cerrado)."""
    return pd.DataFrame(
        [{"lead_id": i, "puntos": p, "cerrado": c, "fecha_registro": fecha} for i, p, c in leads]
    )


# --------------------------------------------------------------------------------------
# Cupo diario
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("leads", "fraccion", "esperado"),
    [(10, 0.7, 7), (10, 1.0, 10), (13, 0.5, 7), (1, 0.5, 1), (0, 0.7, 1)],
)
def test_el_cupo_redondea_hacia_arriba(leads: int, fraccion: float, esperado: int) -> None:
    # Se redondea hacia arriba para no castigar a la política por un cupo artificialmente corto.
    assert cupo(leads, fraccion) == esperado


# --------------------------------------------------------------------------------------
# Orden de cada política
# --------------------------------------------------------------------------------------


def test_la_llegada_ordena_por_id_correlativo() -> None:
    orden = por_llegada(dia(("HX-3", 9, 0), ("HX-1", 1, 0), ("HX-2", 5, 0)))
    assert list(orden["lead_id"]) == ["HX-1", "HX-2", "HX-3"]


def test_el_puntaje_ordena_de_mayor_a_menor() -> None:
    orden = por_puntaje(dia(("HX-1", 1, 0), ("HX-2", 9, 0), ("HX-3", 5, 0)))
    assert list(orden["lead_id"]) == ["HX-2", "HX-3", "HX-1"]


def test_a_igualdad_de_puntos_manda_la_llegada() -> None:
    orden = por_puntaje(dia(("HX-2", 5, 0), ("HX-1", 5, 0)))
    assert list(orden["lead_id"]) == ["HX-1", "HX-2"]


# --------------------------------------------------------------------------------------
# Cierres capturados
# --------------------------------------------------------------------------------------


def test_el_puntaje_rescata_un_cierre_que_la_llegada_deja_fuera() -> None:
    # El único que cierra llegó de último pero tiene el mejor puntaje: con cupo para dos, la
    # llegada lo pierde y el puntaje lo alcanza. Es el caso que justifica todo el proyecto.
    jornada = [dia(("HX-1", 0, 0), ("HX-2", 0, 0), ("HX-3", 0, 0), ("HX-4", 9, 1))]
    assert cierres_capturados(jornada, por_llegada, 0.5) == 0
    assert cierres_capturados(jornada, por_puntaje, 0.5) == 1


def test_con_cupo_para_todos_ninguna_politica_gana() -> None:
    # Si no sobra nadie por atender, priorizar no puede aportar: se gestionan los mismos leads.
    jornada = [dia(("HX-1", 0, 1), ("HX-2", 9, 1))]
    assert cierres_capturados(jornada, por_llegada, 1.0) == 2
    assert cierres_capturados(jornada, por_puntaje, 1.0) == 2


def test_la_capacidad_se_renueva_cada_dia() -> None:
    # Dos días de dos leads con cupo de uno: caben dos cierres, uno por jornada.
    jornadas = [
        dia(("HX-1", 9, 1), ("HX-2", 0, 0), fecha="2026-03-01"),
        dia(("HX-3", 9, 1), ("HX-4", 0, 0), fecha="2026-03-02"),
    ]
    assert cierres_capturados(jornadas, por_puntaje, 0.5) == 2


def test_el_historico_se_parte_por_dia() -> None:
    completo = pd.concat(
        [
            dia(("HX-1", 0, 0), fecha="2026-03-01"),
            dia(("HX-2", 0, 0), ("HX-3", 0, 0), fecha="2026-03-02"),
        ]
    )
    assert [len(d) for d in dias_de(completo)] == [1, 2]


# --------------------------------------------------------------------------------------
# Control al azar
# --------------------------------------------------------------------------------------


def test_el_azar_queda_entre_la_peor_y_la_mejor_politica() -> None:
    jornada = [dia(("HX-1", 0, 0), ("HX-2", 0, 0), ("HX-3", 0, 0), ("HX-4", 9, 1))]
    azar = cierres_al_azar(jornada, 0.5, repeticiones=50)
    assert 0 <= azar <= 1


def test_la_misma_semilla_da_el_mismo_resultado() -> None:
    # La simulación entra en la documentación: tiene que ser reproducible.
    jornada = [dia(("HX-1", 0, 1), ("HX-2", 9, 1), ("HX-3", 0, 0))]
    primera = cierres_al_azar(jornada, 0.5, repeticiones=30, semilla=7)
    assert primera == cierres_al_azar(jornada, 0.5, repeticiones=30, semilla=7)


# --------------------------------------------------------------------------------------
# Presentación
# --------------------------------------------------------------------------------------


def test_la_comparacion_reporta_la_ganancia_contra_la_llegada() -> None:
    jornada = [dia(("HX-1", 0, 0), ("HX-2", 9, 1))]
    resultado = comparar(jornada, 0.5)
    assert resultado["llegada"] == 0
    assert resultado["puntaje"] == 1
    assert resultado["ganancia"] == 1


def test_la_tabla_usa_coma_decimal() -> None:
    fila = {
        "capacidad": 0.7,
        "llegada": 100,
        "azar": 105.5,
        "puntaje": 120,
        "ganancia": 20,
        "ganancia_pct": 20.0,
    }
    salida = tabla([fila])
    assert "70 % de la demanda" in salida
    assert "105,5" in salida and "+20" in salida and "20,0 %" in salida
