"""La evidencia que cita el extractor tiene que estar en lo que escribió el cliente (TRD 8.1)."""

from __future__ import annotations

import pandas as pd

from app.streamlit_app import lineas_de_evidencia
from pipeline.extract.evidencia import campos_sin_respaldo, normalizar

CLIENTE = ["Financiada. Tengo como 2 millones", "¿Puedo pasar mañana a la sede a verla?"]


def test_la_normalizacion_ignora_tildes_mayusculas_y_puntuacion() -> None:
    assert normalizar("¿Puedo pasar MAÑANA?") == "puedo pasar manana"


def test_un_fragmento_textual_tiene_respaldo_aunque_cambien_tildes_y_signos() -> None:
    evidencia = {"pidio_cita": "puedo pasar manana a la sede", "cuota_inicial_cop": "2 millones"}
    assert campos_sin_respaldo(evidencia, CLIENTE) == []


def test_un_fragmento_inventado_no_tiene_respaldo() -> None:
    assert campos_sin_respaldo({"objecion": "la tasa está muy alta"}, CLIENTE) == ["objecion"]


def test_lo_que_dijo_el_asesor_no_cuenta_como_evidencia_del_cliente() -> None:
    # Pasó de verdad con Gemini: citó un mensaje del asesor para `cliente_respondio`.
    asesor = "¿Sigue interesado? quedo atento"
    assert campos_sin_respaldo({"cliente_respondio": asesor}, CLIENTE) == ["cliente_respondio"]


def test_un_fragmento_puede_cruzar_dos_mensajes() -> None:
    assert campos_sin_respaldo({"intencion": "2 millones puedo pasar"}, CLIENTE) == []


def test_sin_evidencia_no_hay_nada_que_revisar() -> None:
    assert campos_sin_respaldo(None, CLIENTE) == []
    assert campos_sin_respaldo({"objecion": ""}, CLIENTE) == []


def test_la_app_solo_cita_lo_que_tiene_respaldo_en_esa_conversacion() -> None:
    mensajes = pd.DataFrame([
        {"conversacion_id": "C1", "emisor": "cliente", "texto": CLIENTE[1]},
        {"conversacion_id": "C1", "emisor": "asesor", "texto": "Claro, la esperamos"},
        # Otra conversación del mismo lote: no respalda la evidencia de C1.
        {"conversacion_id": "C2", "emisor": "cliente", "texto": "Estoy en centrales"},
    ])  # fmt: skip
    fila = {
        "conversacion_id": "C1",
        "evidencia": {"pidio_cita": "Puedo pasar mañana", "objecion": "Estoy en centrales"},
    }
    lineas = lineas_de_evidencia(fila, mensajes)
    assert lineas[0] == "- `pidio_cita`: «Puedo pasar mañana»"
    assert "no se cita" in lineas[1] and "centrales" not in lineas[1]
