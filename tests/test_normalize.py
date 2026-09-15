"""Pruebas de normalización (TRD 6, 6.1 y 14)."""

from datetime import datetime

import pandas as pd
import pytest

from pipeline.normalize import (
    normalizar_canal,
    normalizar_ciudad,
    normalizar_estado,
    normalizar_leads,
    normalizar_telefono,
    resolver_fecha,
    validar_conversaciones,
)
from pipeline.quality import ColectorCalidad


@pytest.mark.parametrize(
    "entrada",
    ["3104824081", "310 482 4081", "+57 310 4824081", "310-482-4081", " 3104824081 ", "573104824081", "(310) 482-4081"],
)  # fmt: skip
def test_siete_formatos_de_telefono(entrada):
    assert normalizar_telefono(entrada) == "3104824081"


@pytest.mark.parametrize("entrada", ["300123", "6044445555", "", None, float("nan")])
def test_telefono_invalido(entrada):
    assert normalizar_telefono(entrada) is None


def test_canal_y_estado():
    assert normalizar_canal(" META ADS ") == "Meta Ads"
    assert normalizar_canal("formulario web") == "Formulario Web"
    assert normalizar_canal(None) is None
    assert normalizar_estado("SIN GESTION") == "Sin gestión"
    assert normalizar_estado("Cotización enviada") == "Cotización enviada"


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("B/quilla", "Barranquilla"), ("Sta Marta", "Santa Marta"), ("Rio Negro", "Rionegro"),
     ("Bogota DC", "Bogotá D.C."), ("BOGOTA", "Bogotá D.C."), ("Cartagena de Indias", "Cartagena"),
     ("Medellín ", "Medellín"), ("ITAGUI", "Itagüí"), (None, None)],
)  # fmt: skip
def test_ciudad(entrada, esperado):
    assert normalizar_ciudad(entrada) == esperado


def test_cuatro_formatos_de_fecha():
    assert resolver_fecha("2026-08-26 20:28:00", None, True) == (
        datetime(2026, 8, 26, 20, 28),
        "unica",
    )
    assert resolver_fecha("2026-08-15T11:08:00", None, True) == (
        datetime(2026, 8, 15, 11, 8),
        "unica",
    )
    assert resolver_fecha("25-08-2026", None, True) == (datetime(2026, 8, 25), "unica")
    assert resolver_fecha("13/08/2026 10:00", None, True) == (
        datetime(2026, 8, 13, 10),
        "componente_mayor_12",
    )


def test_fecha_ambigua_por_ventana_coherencia_y_defecto():
    assert resolver_fecha("05/08/2026 10:30", None, True) == (
        datetime(2026, 8, 5, 10, 30),
        "ventana",
    )
    assert resolver_fecha("09/08/2026 10:00", "2026-08-10 12:00:00", True) == (
        datetime(2026, 8, 9, 10),
        "coherencia",
    )
    assert resolver_fecha("08/09/2026 10:00", "2026-08-20 09:00:00", False) == (
        datetime(2026, 9, 8, 10),
        "coherencia",
    )
    assert resolver_fecha("09/08/2026 10:00", None, True) == (
        datetime(2026, 8, 9, 10),
        "por_defecto",
    )


def test_fecha_invalida():
    assert resolver_fecha("2026-08-33 10:00:00", None, True) == (None, "invalida")


def _lead(**cambios):
    base = {
        "lead_id": "LD-1", "fecha_registro": "2026-08-10 10:00:00", "canal": "whatsapp", "empresa_id": "EMP-01",
        "punto_venta_id": "PV-001", "nombre_cliente": "  ana PÉREZ ", "telefono": "+57 310 4824081",
        "email": None, "ciudad": "medellin", "modelo_interes_texto": "Honda Navi", "estado_gestion": "contactado",
        "fecha_primer_contacto": "2026-08-10 11:00:00", "campania": None,
    }  # fmt: skip
    base.update(cambios)
    return base


def test_normalizar_leads_excluye_repetidos_y_prueba():
    crudos = pd.DataFrame([
        _lead(),
        _lead(),  # repetido
        _lead(lead_id="LD-2", nombre_cliente="prueba prueba", telefono="300123", canal=None),
    ])  # fmt: skip
    colector = ColectorCalidad()
    leads = normalizar_leads(crudos, colector)
    assert list(leads["lead_id"]) == ["LD-1"]
    fila = leads.iloc[0]
    assert (fila["canal"], fila["nombre"], fila["telefono"], fila["ciudad"]) == (
        "WhatsApp",
        "Ana Pérez",
        "3104824081",
        "Medellín",
    )
    assert fila["fecha_registro"].tzinfo is not None
    tipos = colector.resumen()
    assert tipos["lead_repetido"] == 1 and tipos["registro_prueba"] == 1


def test_banderas_de_validacion_cruzada():
    crudos = pd.DataFrame([
        _lead(lead_id="LD-A", fecha_primer_contacto="2026-08-09 09:00:00"),  # contacto antes del registro
        _lead(lead_id="LD-B", fecha_primer_contacto=None),  # gestionado sin fecha de contacto
        _lead(lead_id="LD-C", estado_gestion="Sin gestión"),  # sin gestión con contacto
    ])  # fmt: skip
    colector = ColectorCalidad()
    normalizar_leads(crudos, colector)
    assert colector.banderas_de("LD-A") == ["contacto_antes_de_registro"]
    assert colector.banderas_de("LD-B") == ["estado_sin_fecha_contacto"]
    assert colector.banderas_de("LD-C") == ["sin_gestion_con_contacto"]


def test_conversacion_antes_de_registro_y_huerfana():
    colector = ColectorCalidad()
    leads = normalizar_leads(pd.DataFrame([_lead()]), colector)
    conversaciones = [
        {
            "conversacion_id": "C-1",
            "lead_id": "LD-1",
            "fecha_inicio": "2026-08-09 08:00:00",
            "mensajes": [],
        },
        {
            "conversacion_id": "C-2",
            "lead_id": "LD-999",
            "fecha_inicio": "2026-08-11 08:00:00",
            "mensajes": [],
        },
    ]
    validar_conversaciones(leads, conversaciones, colector)
    assert "conversacion_antes_de_registro" in colector.banderas_de("LD-1")
    assert colector.resumen()["conversacion_huerfana"] == 1
