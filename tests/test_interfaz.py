"""La interfaz por el camino real de los datos (HU-01, HU-02).

`test_app.py` prueba las funciones de presentación con filas armadas a mano, y por eso no vio el
defecto del detalle: con los datos reales, un nulo llega de PostgREST, pasa por un DataFrame y sale
como `NaN`. Aquí los datos vienen del Supabase **local** con las mismas funciones que usa la app, y
la app se ejecuta de verdad con `AppTest`, sin navegador.

Igual que `test_aislamiento.py`, no sale a internet y se omite si la base no está en ejecución.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.streamlit_app import fechas_disponibles, frase_de_apertura, lead_de, leads_de, tabla_de
from tests.test_aislamiento import _sesion, credenciales

APP = Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py"
EMPRESAS = ("emp01", "emp02", "emp03")

# Lo que nunca debe llegar a la pantalla: un nulo impreso o una cifra vacía presentada como dato.
IMPRESIONES_DE_NULO = ("nan", "None", "<NA>", "— de inicial")


def vistas_de(sb) -> list[tuple[str, object, bool]]:
    """Las listas que puede abrir un gerente: la de la empresa y la de cada asesor."""
    corte = fechas_disponibles(sb)[0]
    empresa = leads_de(sb, corte, None)
    vistas = [("empresa", empresa, True)]
    for asesor_id in sorted(empresa["asesor_id"].dropna().unique()):
        vistas.append((asesor_id, leads_de(sb, corte, asesor_id), False))
    return vistas


@pytest.mark.parametrize("empresa", EMPRESAS)
def test_ningun_lead_rompe_la_lista_ni_la_frase(empresa: str) -> None:
    sb = _sesion(f"gerente.{empresa}@example.com")
    corte = fechas_disponibles(sb)[0]
    fallos, revisados = [], 0
    for nombre, df, con_asesor in vistas_de(sb):
        tabla_de(df[df["estado"] == "asignado"], corte, con_asesor=con_asesor)
        for lead_id in df["lead_id"]:
            revisados += 1
            try:
                frase = frase_de_apertura(lead_de(df, lead_id), corte)
            except Exception as error:  # se juntan todos para ver el alcance, no solo el primero
                fallos.append(f"{nombre}/{lead_id}: {error!r}")
                continue
            if any(marca in frase for marca in IMPRESIONES_DE_NULO):
                fallos.append(f"{nombre}/{lead_id}: {frase}")
    assert revisados, "no llegó ningún lead: la prueba no estaría comprobando nada"
    assert not fallos, f"{len(fallos)} de {revisados}, por ejemplo: {fallos[:3]}"


def test_el_asesor_puede_abrir_el_detalle_de_todos_sus_leads() -> None:
    # La app completa, como la usa un asesor: inicia sesión y abre uno por uno los leads de su
    # lista en el detalle, incluidos los Fríos del final, que eran los que fallaban.
    url, llave, password = credenciales()
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60)
    at.secrets["SUPABASE_URL"] = url
    at.secrets["SUPABASE_ANON_KEY"] = llave
    at.run()
    at.text_input[0].input("asesor.as001@example.com")
    at.text_input[1].input(password)
    at.button[0].click().run()
    if not at.session_state["sesion_iniciada"]:
        pytest.skip("No se pudo iniciar sesión en la app: ¿están creados los usuarios de demo?")
    assert not at.exception, at.exception

    opciones = selector_de_lead(at).options
    assert opciones, "la lista del asesor llegó vacía: la prueba no estaría comprobando nada"
    for opcion in opciones:
        selector_de_lead(at).set_value(opcion).run()
        assert not at.exception, f"{opcion}: {at.exception[0].message}"


def selector_de_lead(at):
    """El selector del detalle. Se busca de nuevo tras cada recarga, porque se vuelve a crear."""
    return next(s for s in at.selectbox if s.label == "Lead")
