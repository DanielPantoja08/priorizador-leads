"""Pruebas del acceso a PostgreSQL: conversión de tipos y armado del upsert.

No abren conexión: `upsert` se prueba con un cursor de mentira que guarda lo que habría ejecutado.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from psycopg.types.json import Jsonb

from pipeline.db import a_python, upsert


class CursorFalso:
    """Guarda la consulta y las filas de `executemany` en lugar de enviarlas a la base."""

    def __init__(self) -> None:
        self.consulta: object | None = None
        self.filas: list[dict] = []
        self.llamadas = 0

    def executemany(self, consulta, filas) -> None:
        self.consulta = consulta
        self.filas = list(filas)
        self.llamadas += 1

    def sql(self) -> str:
        return self.consulta.as_string()


# --------------------------------------------------------------------------------------
# a_python
# --------------------------------------------------------------------------------------


def test_los_nulos_de_pandas_y_numpy_se_vuelven_none() -> None:
    # Postgres no entiende NaN ni NaT en una columna de texto o de fecha: deben viajar como NULL.
    assert a_python(None) is None
    assert a_python(float("nan")) is None
    assert a_python(pd.NaT) is None


def test_los_numeros_de_numpy_se_vuelven_numeros_de_python() -> None:
    # psycopg no adapta np.int64; sin esta conversión el insert falla.
    assert a_python(np.int64(7)) == 7
    assert type(a_python(np.int64(7))) is int
    assert a_python(np.float64(1.5)) == 1.5


def test_un_diccionario_viaja_como_jsonb() -> None:
    assert isinstance(a_python({"factor": "cita"}), Jsonb)


@pytest.mark.parametrize("valor", [["a", "b"], ("a", "b"), {"a"}])
def test_las_secuencias_viajan_como_lista(valor: object) -> None:
    assert a_python(valor) == list(valor) if not isinstance(valor, set) else True
    assert isinstance(a_python(valor), list)


def test_los_valores_normales_no_se_tocan() -> None:
    assert a_python("WhatsApp") == "WhatsApp"
    assert a_python(3) == 3
    assert a_python(True) is True


# --------------------------------------------------------------------------------------
# upsert
# --------------------------------------------------------------------------------------


def test_sin_filas_no_se_ejecuta_nada() -> None:
    cur = CursorFalso()
    assert upsert(cur, "lead", [], ["lead_id"]) == 0
    assert cur.llamadas == 0


def test_actualiza_las_columnas_que_no_son_clave() -> None:
    cur = CursorFalso()
    filas = [{"lead_id": "LD-1", "estado_gestion": "Contactado"}]
    assert upsert(cur, "lead", filas, ["lead_id"]) == 1
    sql = cur.sql()
    assert 'insert into "public"."lead"' in sql
    assert 'on conflict ("lead_id") do update set' in sql
    assert '"estado_gestion" = excluded."estado_gestion"' in sql
    # La clave no se reasigna: ya vale lo mismo y actualizarla no aporta nada.
    assert '"lead_id" = excluded."lead_id"' not in sql


def test_si_todo_es_clave_no_hay_nada_que_actualizar() -> None:
    # `do update set` sin columnas sería SQL inválido; el caso se resuelve con `do nothing`.
    cur = CursorFalso()
    filas = [{"modelo_id": "SKU-1", "punto_venta_id": "PV-001"}]
    assert upsert(cur, "modelo_punto_venta", filas, ["modelo_id", "punto_venta_id"]) == 1
    assert "do nothing" in cur.sql()


def test_las_filas_se_convierten_antes_de_enviarse() -> None:
    cur = CursorFalso()
    upsert(cur, "lead", [{"lead_id": "LD-1", "orden": np.int64(3), "ciudad": pd.NaT}], ["lead_id"])
    assert cur.filas == [{"lead_id": "LD-1", "orden": 3, "ciudad": None}]
    assert type(cur.filas[0]["orden"]) is int


def test_se_envian_todas_las_filas_en_una_sola_llamada() -> None:
    # executemany en vez de un insert por fila: son miles de leads en cada corrida.
    cur = CursorFalso()
    filas = [{"lead_id": f"LD-{i}", "canal": "web"} for i in range(50)]
    assert upsert(cur, "lead", filas, ["lead_id"]) == 50
    assert cur.llamadas == 1
    assert len(cur.filas) == 50
