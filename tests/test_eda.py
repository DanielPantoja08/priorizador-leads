"""Pruebas de las utilidades de medición del EDA (sin red ni base de datos)."""

from datetime import datetime

import pytest

from eda.comun import clase_barras, normalizar_telefono, resolver_fecha, wilson


@pytest.mark.parametrize(
    "entrada",
    [
        "3104824081",
        "310 482 4081",
        "+57 310 4824081",
        "310-482-4081",
        " 3104824081 ",
        "573104824081",
        "(310) 482-4081",
    ],
)
def test_siete_formatos_de_telefono(entrada):
    assert normalizar_telefono(entrada) == "3104824081"


@pytest.mark.parametrize("entrada", ["300123", "6044445555", "", None, float("nan")])
def test_telefono_invalido(entrada):
    assert normalizar_telefono(entrada) is None


def test_wilson_contiene_la_tasa():
    p, bajo, alto = wilson(197, 2200)
    assert bajo < p < alto
    assert round(p, 4) == 0.0895


def test_wilson_sin_muestra():
    assert wilson(0, 0) is None


def test_clase_barras():
    assert clase_barras("13/08/2026 10:00") == "ddmm"
    assert clase_barras("08/13/2026 10:00") == "mmdd"
    assert clase_barras("05/05/2026 10:00") == "igual"
    assert clase_barras("05/08/2026 10:00") == "ambigua"


def test_fecha_determinada_por_componente_mayor_a_12():
    fecha, motivo = resolver_fecha("08/13/2026 10:00", None, es_registro=True)
    assert fecha == datetime(2026, 8, 13, 10, 0)
    assert motivo == "componente_mayor_12"


def test_fecha_resuelta_por_ventana():
    # 05/08 como mm/dd sería 8 de mayo, fuera de la ventana agosto-septiembre.
    fecha, motivo = resolver_fecha("05/08/2026 10:30", None, es_registro=True)
    assert fecha == datetime(2026, 8, 5, 10, 30)
    assert motivo == "ventana"


def test_fecha_resuelta_por_coherencia_con_contacto():
    # 09/08: 9 de agosto o 8 de septiembre. El contacto es el 10 de agosto -> registro el 9 de agosto.
    fecha, motivo = resolver_fecha("09/08/2026 10:00", "2026-08-10 12:00:00", es_registro=True)
    assert fecha == datetime(2026, 8, 9, 10, 0)
    assert motivo == "coherencia"


def test_fecha_contacto_resuelta_por_coherencia_con_registro():
    # Contacto 08/09: 8 de septiembre o 9 de agosto. Registro el 20 de agosto -> contacto el 8 de septiembre.
    fecha, motivo = resolver_fecha("08/09/2026 10:00", "2026-08-20 09:00:00", es_registro=False)
    assert fecha == datetime(2026, 9, 8, 10, 0)
    assert motivo == "coherencia"


def test_fecha_empate_usa_dd_mm():
    fecha, motivo = resolver_fecha("09/08/2026 10:00", None, es_registro=True)
    assert fecha == datetime(2026, 8, 9, 10, 0)
    assert motivo == "por_defecto"


def test_fecha_invalida():
    assert resolver_fecha("2026-08-33 10:00:00", None, es_registro=True) == (None, "invalida")
