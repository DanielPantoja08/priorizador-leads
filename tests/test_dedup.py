"""Pruebas de deduplicación por empresa (TRD 7 y 14)."""

from datetime import datetime

import pandas as pd

from pipeline.config import ZONA
from pipeline.dedup import deduplicar, elegir_principal
from pipeline.quality import ColectorCalidad


def _lead(
    lead_id,
    empresa,
    telefono,
    dia,
    estado="Contactado",
    nombre="Ana Pérez",
    canal="WhatsApp",
    email=None,
):
    return {
        "lead_id": lead_id, "empresa_id": empresa, "telefono": telefono, "email": email, "nombre": nombre,
        "ciudad": "Medellín", "canal": canal, "estado_gestion": estado,
        "fecha_registro": datetime(2026, 8, dia, 10, tzinfo=ZONA),
    }  # fmt: skip


def _deduplicar(filas):
    colector = ColectorCalidad()
    clientes, leads = deduplicar(pd.DataFrame(filas, dtype="object"), colector)
    return clientes, leads, colector


def test_agrupa_dentro_de_la_empresa_y_multicanal():
    clientes, leads, _ = _deduplicar([
        _lead("LD-1", "EMP-01", "3001112233", 1, canal="WhatsApp"),
        _lead("LD-2", "EMP-01", "3001112233", 5, canal="Meta Ads"),
    ])  # fmt: skip
    assert len(clientes) == 1
    assert clientes.iloc[0]["leads"] == 2 and clientes.iloc[0]["canales"] == 2


def test_telefono_compartido_entre_empresas_no_se_fusiona():
    clientes, _, _ = _deduplicar([
        _lead("LD-1", "EMP-01", "3001112233", 1),
        _lead("LD-2", "EMP-02", "3001112233", 2),
    ])  # fmt: skip
    assert sorted(clientes["empresa_id"]) == ["EMP-01", "EMP-02"]


def test_principal_es_el_mas_reciente_no_descartado():
    _, leads, _ = _deduplicar([
        _lead("LD-1", "EMP-01", "3001112233", 1),
        _lead("LD-2", "EMP-01", "3001112233", 3),
        _lead("LD-3", "EMP-01", "3001112233", 9, estado="Descartado"),
    ])  # fmt: skip
    assert leads.set_index("lead_id")["es_principal"].to_dict() == {
        "LD-1": False,
        "LD-2": True,
        "LD-3": False,
    }


def test_todos_descartados_usa_el_mas_reciente():
    grupo = [
        _lead("LD-1", "EMP-01", "3001112233", 1, estado="Descartado"),
        _lead("LD-2", "EMP-01", "3001112233", 4, estado="Descartado"),
    ]
    assert elegir_principal(grupo) == "LD-2"


def test_clave_secundaria_por_email_y_nombre_mas_largo():
    clientes, _, _ = _deduplicar([
        _lead("LD-1", "EMP-01", None, 1, nombre="A. Pérez", email="ana@x.co"),
        _lead("LD-2", "EMP-01", None, 2, nombre="Ana Pérez Gómez", email="ana@x.co"),
    ])  # fmt: skip
    assert list(clientes["clave_dedup"]) == ["email:ana@x.co"]
    assert clientes.iloc[0]["nombre"] == "Ana Pérez Gómez"


def test_posible_colision_de_telefono():
    _, _, colector = _deduplicar([
        _lead("LD-1", "EMP-01", "3001112233", 1, nombre="Ana Pérez"),
        _lead("LD-2", "EMP-01", "3001112233", 2, nombre="Jorge Quintero"),
    ])  # fmt: skip
    assert colector.banderas_de("LD-1") == ["posible_colision_telefono"]
