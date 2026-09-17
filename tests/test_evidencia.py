"""La evidencia que cita el extractor tiene que estar en lo que escribió el cliente (TRD 8.1)."""

from __future__ import annotations

import pandas as pd

from app.streamlit_app import lineas_de_evidencia
from pipeline.extract.evidencia import campos_sin_respaldo, normalizar

CLIENTE = ["Financiada. Tengo como 2 millones", "¿Puedo pasar mañana a la sede a verla?"]
ASESOR = "¿Sigue interesado? quedo atento"
MENSAJES = [
    {"emisor": "cliente", "texto": CLIENTE[0]},
    {"emisor": "cliente", "texto": CLIENTE[1]},
    {"emisor": "asesor", "texto": ASESOR},
]


def test_la_normalizacion_ignora_tildes_mayusculas_y_puntuacion() -> None:
    assert normalizar("¿Puedo pasar MAÑANA?") == "puedo pasar manana"


def test_un_fragmento_textual_tiene_respaldo_aunque_cambien_tildes_y_signos() -> None:
    evidencia = {"pidio_cita": "puedo pasar manana a la sede", "cuota_inicial_cop": "2 millones"}
    assert campos_sin_respaldo(evidencia, MENSAJES) == []


def test_un_fragmento_inventado_no_tiene_respaldo() -> None:
    assert campos_sin_respaldo({"objecion": "la tasa está muy alta"}, MENSAJES) == ["objecion"]


def test_lo_que_dijo_el_asesor_no_cuenta_como_evidencia_del_cliente() -> None:
    assert campos_sin_respaldo({"objecion": ASESOR}, MENSAJES) == ["objecion"]


def test_que_el_cliente_no_respondio_se_prueba_con_el_mensaje_del_asesor() -> None:
    # Sin respuesta del cliente no hay palabras suyas que citar: la evidencia es lo que quedó sin
    # contestar. Marcarlo como sin respaldo era un falso positivo (5 de los 10 casos reales).
    assert campos_sin_respaldo({"cliente_respondio": ASESOR}, MENSAJES) == []


def test_ni_siquiera_ese_campo_acepta_texto_que_no_esta_en_la_conversacion() -> None:
    # Pasó de verdad con Gemini: devolvió el nombre del campo como fragmento.
    evidencia = {"cliente_respondio": "cliente_respondio"}
    assert campos_sin_respaldo(evidencia, MENSAJES) == ["cliente_respondio"]


def test_un_fragmento_puede_cruzar_dos_mensajes() -> None:
    assert campos_sin_respaldo({"intencion": "2 millones puedo pasar"}, MENSAJES) == []


def test_sin_evidencia_no_hay_nada_que_revisar() -> None:
    assert campos_sin_respaldo(None, MENSAJES) == []
    assert campos_sin_respaldo({"objecion": ""}, MENSAJES) == []


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


def test_el_encabezado_de_la_transcripcion_no_cuenta_como_parte_de_la_cita() -> None:
    # El modelo ve «asesor [10:49]: texto» y a veces copia la línea entera.
    evidencia = {"cliente_respondio": f"asesor [10:49]: {ASESOR}"}
    assert campos_sin_respaldo(evidencia, MENSAJES) == []
    # Quitar el encabezado no vuelve válida una cita del asesor en un campo del cliente.
    assert campos_sin_respaldo({"intencion": f"asesor [10:49]: {ASESOR}"}, MENSAJES) == [
        "intencion"
    ]


def test_una_errata_al_copiar_no_vuelve_falsa_la_cita() -> None:
    # Pasó de verdad con Gemini: «visitiar» por «visitar», «não» por «no».
    mensajes = [{"emisor": "cliente", "texto": "¿A qué hora los puedo visitar hoy?"}]
    assert (
        campos_sin_respaldo({"pidio_cita": "¿A qué hora los puedo visitiar hoy?"}, mensajes) == []
    )


def test_una_frase_parecida_pero_distinta_no_pasa_por_errata() -> None:
    mensajes = [{"emisor": "cliente", "texto": "¿A qué hora los puedo visitar hoy?"}]
    assert campos_sin_respaldo({"pidio_cita": "quiero pasar mañana a la sede"}, mensajes) == [
        "pidio_cita"
    ]
