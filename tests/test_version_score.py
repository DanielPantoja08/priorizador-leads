"""La versión de puntaje se ordena por número, no por texto (v10 va después de v2).

La prueba de la vista usa el Supabase **local** y se omite si no está en ejecución. Solo se conecta
a 127.0.0.1 y trabaja dentro de una transacción que se deshace: no deja filas ni toca la base remota
aunque `DATABASE_URL` apunte a ella.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import pytest
from dotenv import dotenv_values

from pipeline.scoring import VERSION_SCORE
from tests.test_aislamiento import RAIZ

FORMATO = r"v[1-9][0-9]*"  # el mismo que exige el check de score.version_score


def test_la_version_vigente_tiene_el_formato_que_exige_la_base() -> None:
    assert re.fullmatch(FORMATO, VERSION_SCORE)


def conexion_local():
    """Conexión al Postgres local, o se omite la prueba."""
    psycopg = pytest.importorskip("psycopg")
    url = dotenv_values(RAIZ / ".env").get("DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if urlparse(url).hostname not in ("127.0.0.1", "localhost"):
        pytest.skip("Sin DATABASE_URL local: esta prueba no se corre contra una base remota.")
    try:
        return psycopg.connect(url, connect_timeout=3)
    except psycopg.OperationalError as error:
        pytest.skip(f"Supabase local no está en ejecución: {error}")


def test_la_vista_elige_v10_antes_que_v2() -> None:
    with conexion_local() as conn:
        try:
            fila = conn.execute(
                "select lead_id, fecha_corte from public.v_mis_leads_hoy "
                "where version_score is not null limit 1"
            ).fetchone()
            if fila is None:
                pytest.skip("La base local no tiene puntajes: corra el pipeline primero.")
            # Una v10 del mismo lead y la misma fecha: como texto quedaría detrás de 'v2'.
            conn.execute(
                "insert into public.score (lead_id, fecha_corte, version_score, empresa_id, "
                "prioridad, temperatura) "
                "select lead_id, fecha_corte, 'v10', empresa_id, prioridad, temperatura "
                "from public.score where lead_id = %s and fecha_corte = %s limit 1",
                fila,
            )
            elegida = conn.execute(
                "select version_score from public.v_mis_leads_hoy "
                "where lead_id = %s and fecha_corte = %s",
                fila,
            ).fetchone()
            assert elegida == ("v10",)
        finally:
            conn.rollback()


@pytest.mark.parametrize("version", ["2", "v02", "v2b", "V3"])
def test_la_base_rechaza_versiones_sin_formato(version: str) -> None:
    psycopg = pytest.importorskip("psycopg")
    with conexion_local() as conn:
        try:
            fila = conn.execute(
                "select lead_id, fecha_corte, empresa_id from public.score limit 1"
            ).fetchone()
            if fila is None:
                pytest.skip("La base local no tiene puntajes: corra el pipeline primero.")
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(
                    "insert into public.score (lead_id, fecha_corte, version_score, empresa_id) "
                    "values (%s, %s, %s, %s)",
                    (fila[0], fila[1], version, fila[2]),
                )
        finally:
            conn.rollback()
