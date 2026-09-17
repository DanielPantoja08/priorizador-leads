"""El asesor ve solo la asignación vigente, la de la última fecha de corte (TRD 12).

Usa el Supabase **local** y se omite si no está. Todo ocurre en una transacción que se deshace: se
crea una fecha de corte nueva en la que un cliente de AS-001 pasa a otro asesor, y se consulta con
la sesión de cada uno simulada en la base (rol `authenticated` y su JWT), igual que PostgREST.
"""

from __future__ import annotations

import json

import pytest

from tests.test_version_score import conexion_local

NUEVA_FECHA = "2099-01-01"


def como_usuario(conn, user_id: str) -> None:
    """Hace que lo que sigue en la transacción pase por RLS como ese usuario."""
    conn.execute("reset role")
    reclamo = json.dumps({"sub": user_id, "role": "authenticated"})
    conn.execute("select set_config('request.jwt.claims', %s, true)", (reclamo,))
    conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (user_id,))
    conn.execute("set local role authenticated")


def uno(conn, sql: str, parametros: tuple = ()) -> int:
    return conn.execute(sql, parametros).fetchone()[0]


@pytest.fixture
def traspaso():
    """Un lead de AS-001 que en una fecha de corte nueva pasa a otro asesor de su punto de venta."""
    with conexion_local() as conn:
        try:
            fila = conn.execute(
                "select a.lead_id, a.empresa_id, a.fecha_corte, u.user_id, otro.asesor_id, ou.user_id "
                "from public.asignacion a "
                "join public.usuario_empresa u on u.asesor_id = a.asesor_id "
                "join public.asesor yo on yo.asesor_id = a.asesor_id "
                "join public.asesor otro on otro.punto_venta_id = yo.punto_venta_id "
                "  and otro.asesor_id <> yo.asesor_id and otro.activo "
                "join public.usuario_empresa ou on ou.asesor_id = otro.asesor_id "
                "where a.asesor_id = 'AS-001' and a.estado = 'asignado' limit 1"
            ).fetchone()
            if fila is None:
                pytest.skip("Sin asignaciones o usuarios de demo en la base local.")
            lead, empresa, fecha, yo, otro, otro_usuario = fila
            conn.execute(
                "insert into public.asignacion (fecha_corte, lead_id, empresa_id, asesor_id, orden, "
                "estado) values (%s, %s, %s, %s, 1, 'asignado')",
                (NUEVA_FECHA, lead, empresa, otro),
            )
            yield conn, lead, fecha, str(yo), str(otro_usuario)
        finally:
            conn.rollback()


def test_el_asesor_deja_de_ver_un_cliente_que_hoy_tiene_otro(traspaso) -> None:
    conn, lead, _, yo, _ = traspaso
    como_usuario(conn, yo)
    assert uno(conn, "select count(*) from public.lead where lead_id = %s", (lead,)) == 0


def test_el_asesor_no_ve_sus_filas_de_fechas_anteriores(traspaso) -> None:
    conn, _, fecha, yo, _ = traspaso
    como_usuario(conn, yo)
    assert uno(conn, "select count(*) from public.asignacion where fecha_corte = %s", (fecha,)) == 0


def test_el_asesor_que_lo_tiene_hoy_si_lo_ve(traspaso) -> None:
    conn, lead, _, _, otro = traspaso
    como_usuario(conn, otro)
    assert uno(conn, "select count(*) from public.lead where lead_id = %s", (lead,)) == 1
    assert (
        uno(conn, "select count(*) from public.asignacion where fecha_corte = %s", (NUEVA_FECHA,))
        == 1
    )
