"""Aislamiento entre empresas de extremo a extremo (RF-12, HU-05, TRD 12).

Esta es la única prueba que toca un servicio: el Supabase **local**. No sale a internet. Si la
base no está en ejecución o faltan las credenciales de demostración, la prueba se omite en vez de
fallar, para que `pytest` siga siendo verde en una máquina sin Docker.

Comprueba lo que promete HU-05: que un usuario de EMP-01 no puede ver filas de otra empresa ni
desde la app ni consultando directamente con su sesión, y que un asesor solo ve sus propios leads.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
SECRETS = RAIZ / ".streamlit" / "secrets.toml"

# Tablas con una columna empresa_id y política por empresa.
TABLAS_POR_EMPRESA = ("lead", "cliente", "score", "asignacion", "conversacion", "senales_lead")


def credenciales() -> tuple[str, str, str]:
    """(url, llave anónima, contraseña de demostración). Omite la prueba si falta algo."""
    load_dotenv(RAIZ / ".env")
    url = os.getenv("SUPABASE_URL", "").strip()
    llave = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if (not url or not llave) and SECRETS.exists():
        datos = tomllib.loads(SECRETS.read_text(encoding="utf-8"))
        url = url or str(datos.get("SUPABASE_URL", ""))
        llave = llave or str(datos.get("SUPABASE_ANON_KEY", ""))
    password = os.getenv("DEMO_PASSWORD", "").strip()
    if not (url and llave and password):
        pytest.skip("Sin credenciales locales de Supabase: se omite la prueba de aislamiento.")
    return url, llave, password


@pytest.fixture(scope="module")
def sesion_gerente_emp01():
    """Cliente autenticado como el gerente de EMP-01."""
    return _sesion("gerente.emp01@example.com")


@pytest.fixture(scope="module")
def sesion_asesor_emp01():
    """Cliente autenticado como el primer asesor de EMP-01.

    Hay una cuenta por asesor y el correo se deriva del id (AS-001 -> asesor.as001@example.com).
    """
    return _sesion("asesor.as001@example.com")


def _sesion(correo: str):
    url, llave, password = credenciales()
    supabase = pytest.importorskip("supabase")
    try:
        cliente = supabase.create_client(url, llave)
        cliente.auth.sign_in_with_password({"email": correo, "password": password})
    except Exception as error:  # base apagada o usuarios de demostración sin crear
        pytest.skip(f"No se pudo iniciar sesión como {correo}: {error!r}")
    return cliente


@pytest.mark.parametrize("tabla", TABLAS_POR_EMPRESA)
def test_solo_se_ven_filas_de_la_propia_empresa(sesion_gerente_emp01, tabla: str) -> None:
    filas = sesion_gerente_emp01.table(tabla).select("empresa_id").execute().data
    assert filas, f"{tabla} no devolvió filas: la prueba no estaría comprobando nada"
    assert {f["empresa_id"] for f in filas} == {"EMP-01"}


def test_la_vista_diaria_tambien_aisla(sesion_gerente_emp01) -> None:
    # La vista es `security_invoker`, así que hereda las políticas en lugar de saltárselas.
    filas = sesion_gerente_emp01.table("v_mis_leads_hoy").select("empresa_id").execute().data
    assert filas
    assert {f["empresa_id"] for f in filas} == {"EMP-01"}


def test_un_telefono_compartido_aparece_una_sola_vez(sesion_gerente_emp01) -> None:
    """Una persona que existe en dos empresas son dos clientes independientes (HU-05)."""
    clientes = sesion_gerente_emp01.table("cliente").select("telefono").execute().data
    telefonos = [c["telefono"] for c in clientes if c["telefono"]]
    assert len(telefonos) == len(set(telefonos))


def test_el_asesor_solo_ve_sus_propios_leads(sesion_asesor_emp01) -> None:
    perfil = sesion_asesor_emp01.table("usuario_empresa").select("asesor_id").execute().data
    suyo = perfil[0]["asesor_id"]
    filas = sesion_asesor_emp01.table("asignacion").select("asesor_id").execute().data
    assert filas, "el asesor de demostración no tiene leads asignados"
    assert {f["asesor_id"] for f in filas} == {suyo}


def test_las_conversaciones_huerfanas_no_son_visibles(sesion_gerente_emp01) -> None:
    """Sin empresa no hay dueño, así que no las ve nadie desde la app."""
    filas = sesion_gerente_emp01.table("conversacion").select("es_huerfana").execute().data
    assert filas
    assert not any(f["es_huerfana"] for f in filas)


def test_el_usuario_no_puede_escribir(sesion_gerente_emp01) -> None:
    """La app es de solo lectura: no hay políticas de insert, update ni delete."""
    from postgrest.exceptions import APIError

    with pytest.raises(APIError):
        sesion_gerente_emp01.table("lead").insert({"lead_id": "LD-PRUEBA"}).execute()
