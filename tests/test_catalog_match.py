"""Pruebas de la normalización del modelo contra el catálogo (TRD 6.2 y 14)."""

import pandas as pd
import pytest

from pipeline.catalog_match import Catalogo


@pytest.fixture(scope="module")
def catalogo():
    filas = [
        ("SKU-004", "Honda", "Navi", "PV-001|PV-002"),
        ("SKU-005", "Honda", "Dio 110", "PV-001"),
        ("SKU-008", "Bajaj", "Pulsar NS 125", "PV-001"),
        ("SKU-009", "Bajaj", "Pulsar NS 160", "PV-001"),
        ("SKU-010", "Bajaj", "Pulsar RS 200", "PV-002"),
        ("SKU-013", "Suzuki", "GN 125", "PV-003"),
        ("SKU-016", "Suzuki", "Best 125", "PV-003"),
        ("SKU-018", "AKT", "Dynamic R3 125", "PV-001"),
        ("SKU-019", "AKT", "TTR 200", "PV-004"),
    ]
    return Catalogo(
        pd.DataFrame(
            {
                "sku": [f[0] for f in filas],
                "marca": [f[1] for f in filas],
                "linea": [f[2] for f in filas],
                "cilindraje": ["125"] * len(filas),
                "segmento": ["Trabajo"] * len(filas),
                "precio_lista": ["7000000"] * len(filas),
                "puntos_venta_disponibles": [f[3] for f in filas],
                "unidades_disponibles": ["10"] * len(filas),
            }
        )
    )


@pytest.mark.parametrize(
    ("texto", "sku"),
    [("Suzuky GN 125", "SKU-013"), ("A.K.T Dynamic R3 125", "SKU-018"), ("TTR 200", "SKU-019"),
     ("Honda Navi 2026", "SKU-004"), ("honda  NAVI", "SKU-004"), ("Pulsar NS 125", "SKU-008")],
)  # fmt: skip
def test_asigna_sku(catalogo, texto, sku):
    assert catalogo.resolver(texto).sku == sku


def test_varias_lineas_empatadas_quedan_como_marca(catalogo):
    resultado = catalogo.resolver("Bajaj Pulsar")
    assert (resultado.sku, resultado.marca, resultado.regla) == (None, "Bajaj", "modelo_ambiguo")


def test_solo_marca(catalogo):
    resultado = catalogo.resolver("Honda")
    assert (resultado.sku, resultado.marca, resultado.regla) == (None, "Honda", "modelo_ambiguo")


def test_modelo_faltante(catalogo):
    assert catalogo.resolver(None).regla == "modelo_faltante"
    assert catalogo.resolver("  ").regla == "modelo_faltante"


def test_disponibilidad_en_punto_venta(catalogo):
    assert catalogo.disponible("SKU-004", "PV-002") is True
    assert catalogo.disponible("SKU-004", "PV-009") is False
    assert catalogo.disponible(None, "PV-001") is None
