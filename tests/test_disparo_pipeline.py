"""El disparo diario desde la base (pg_cron + pg_net) está programado y protegido.

Usa el Supabase **local** y se omite si no está en ejecución. No llama a GitHub: en local no hay
token en Vault, y la función avisa y no hace la petición.
"""

from __future__ import annotations

import pytest

from tests.test_version_score import conexion_local


def test_la_tarea_diaria_esta_programada_a_las_6_17_de_bogota() -> None:
    with conexion_local() as conn:
        fila = conn.execute(
            "select schedule, command, active from cron.job where jobname = 'pipeline-diario'"
        ).fetchone()
    assert fila == ("17 11 * * *", "select privado.disparar_pipeline()", True)


@pytest.mark.parametrize("rol", ["anon", "authenticated"])
def test_la_app_no_puede_disparar_el_pipeline(rol: str) -> None:
    with conexion_local() as conn:
        (permitido,) = conn.execute(
            "select has_function_privilege(%s, 'privado.disparar_pipeline()', 'execute')", (rol,)
        ).fetchone()
    assert permitido is False


def test_sin_token_no_llama_a_github() -> None:
    with conexion_local() as conn:
        (hay_token,) = conn.execute(
            "select exists (select 1 from vault.secrets where name = 'github_token_pipeline')"
        ).fetchone()
        if hay_token:
            pytest.skip("La base local tiene token: la prueba haría una petición real.")
        antes = conn.execute("select count(*) from net.http_request_queue").fetchone()[0]
        (resultado,) = conn.execute("select privado.disparar_pipeline()").fetchone()
        despues = conn.execute("select count(*) from net.http_request_queue").fetchone()[0]
        conn.rollback()
    assert resultado is None
    assert despues == antes


def test_la_base_acepta_el_disparador_supabase_cron() -> None:
    with conexion_local() as conn:
        try:
            conn.execute(
                "insert into public.ejecucion (estado, disparador) values ('en_curso', 'supabase_cron')"
            )
        finally:
            conn.rollback()
