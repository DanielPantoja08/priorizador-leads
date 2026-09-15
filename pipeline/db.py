"""Acceso a PostgreSQL para el pipeline: conexión, upserts por clave natural y registro de ejecución."""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb


def conectar(database_url: str) -> psycopg.Connection:
    """Conexión con credenciales de servidor. RLS no aplica a este rol: solo la usa el pipeline."""
    return psycopg.connect(database_url)


def a_python(valor: object) -> object:
    """Convierte valores de pandas o numpy a tipos que psycopg adapta (NaN y NaT -> None)."""
    if valor is None:
        return None
    if isinstance(valor, dict):
        return Jsonb(valor)
    if isinstance(valor, (list, tuple, set)):
        return list(valor)
    if isinstance(valor, np.generic):
        valor = valor.item()
    if (isinstance(valor, float) and math.isnan(valor)) or valor is pd.NaT:
        return None
    return valor


def upsert(cur: psycopg.Cursor, tabla: str, filas: Iterable[dict], clave: list[str]) -> int:
    """Inserta o actualiza por clave natural (idempotente). Devuelve la cantidad de filas enviadas."""
    filas = [{k: a_python(v) for k, v in fila.items()} for fila in filas]
    if not filas:
        return 0
    columnas = list(filas[0])
    actualizar = [c for c in columnas if c not in clave]
    if actualizar:
        accion = sql.SQL("update set {}").format(
            sql.SQL(", ").join(
                sql.SQL("{0} = excluded.{0}").format(sql.Identifier(c)) for c in actualizar
            )
        )
    else:
        accion = sql.SQL("nothing")
    consulta = sql.SQL("insert into {tabla} ({columnas}) values ({valores}) on conflict ({clave}) do {accion}").format(
        tabla=sql.Identifier("public", tabla),
        columnas=sql.SQL(", ").join(map(sql.Identifier, columnas)),
        valores=sql.SQL(", ").join(sql.Placeholder(c) for c in columnas),
        clave=sql.SQL(", ").join(map(sql.Identifier, clave)),
        accion=accion,
    )  # fmt: skip
    cur.executemany(consulta, filas)
    return len(filas)


def abrir_ejecucion(conn: psycopg.Connection, disparador: str) -> int:
    """Crea el registro de la corrida y lo confirma de inmediato (queda aunque la corrida falle)."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "insert into public.ejecucion (estado, disparador) values ('en_curso', %s) returning ejecucion_id",
            (disparador,),
        )
        return cur.fetchone()[0]


def cerrar_ejecucion(
    conn: psycopg.Connection,
    ejecucion_id: int,
    estado: str,
    fecha_corte=None,
    conteos: dict | None = None,
    detalle_error: str | None = None,
    llamadas_llm: int = 0,
    errores_llm: int = 0,
) -> None:
    """Cierra el registro con estado, conteos por etapa y, si hubo, el error."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            update public.ejecucion
               set finalizado_en = now(), estado = %s, fecha_corte = %s, conteos = %s,
                   detalle_error = %s, llamadas_llm = %s, errores_llm = %s
             where ejecucion_id = %s
            """,
            (
                estado,
                fecha_corte,
                Jsonb(conteos or {}),
                detalle_error,
                llamadas_llm,
                errores_llm,
                ejecucion_id,
            ),
        )
