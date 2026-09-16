"""Pruebas de la etapa de extracción (TRD 8): qué extractor se arma y quién resolvió cada conversación.

Ninguna prueba sale a la red: el cliente de Gemini se simula, como exige la regla del proyecto.
"""

from __future__ import annotations

import pandas as pd
import pytest

from pipeline.config import Config
from pipeline.extract.etapa import (
    MODELO_GEMINI_POR_DEFECTO,
    _extractor_de,
    construir_extractor,
)
from pipeline.extract.gemini import ExtractorGemini
from pipeline.extract.rules import ExtractorReglas


class CatalogoFalso:
    """Al armar el extractor solo le interesan las marcas del catálogo."""

    def __init__(self, marcas: list[str]) -> None:
        self.modelos = pd.DataFrame({"marca": marcas})


class ClienteFalso:
    """Reemplaza a `genai.Client`: se construye sin credenciales y no llama a nadie."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key


def config(**cambios) -> Config:
    base = {
        "database_url": "postgresql://local",
        "extractor": "reglas",
        "gemini_api_key": None,
        "gemini_model": None,
        "llm_batch_size": 10,
        "llm_max_rpm": 5,
        "fecha_corte": None,
        "ventana_dias": 30,
    }
    return Config(**(base | cambios))


CATALOGO = CatalogoFalso(["Bajaj", "Honda", "Bajaj"])


# --------------------------------------------------------------------------------------
# construir_extractor
# --------------------------------------------------------------------------------------


def test_el_extractor_por_reglas_no_necesita_credenciales() -> None:
    extractor = construir_extractor(config(extractor="reglas"), CATALOGO)
    assert isinstance(extractor, ExtractorReglas)


def test_pedir_gemini_sin_llave_falla_explicando_la_salida() -> None:
    # Fallar en seco es mejor que caer en silencio a las reglas: el usuario pidió IA.
    with pytest.raises(RuntimeError) as error:
        construir_extractor(config(extractor="gemini"), CATALOGO)
    assert "GEMINI_API_KEY" in str(error.value)
    assert "EXTRACTOR=reglas" in str(error.value)


def test_el_extractor_de_gemini_lleva_siempre_el_de_reglas_como_respaldo(monkeypatch) -> None:
    # RNF-06: si el modelo falla, la corrida termina igual con las reglas.
    monkeypatch.setattr("google.genai.Client", ClienteFalso)
    extractor = construir_extractor(config(extractor="gemini", gemini_api_key="llave"), CATALOGO)
    assert isinstance(extractor, ExtractorGemini)
    assert isinstance(extractor.respaldo, ExtractorReglas)


def test_sin_modelo_configurado_se_usa_el_de_por_defecto(monkeypatch) -> None:
    monkeypatch.setattr("google.genai.Client", ClienteFalso)
    extractor = construir_extractor(config(extractor="gemini", gemini_api_key="llave"), CATALOGO)
    assert extractor.modelo == MODELO_GEMINI_POR_DEFECTO


def test_el_modelo_del_entorno_manda(monkeypatch) -> None:
    monkeypatch.setattr("google.genai.Client", ClienteFalso)
    configuracion = config(
        extractor="gemini", gemini_api_key="llave", gemini_model="gemini-3.5-flash"
    )
    assert construir_extractor(configuracion, CATALOGO).modelo == "gemini-3.5-flash"


def test_los_limites_de_peticiones_llegan_al_extractor(monkeypatch) -> None:
    # El extractor no guarda las peticiones por minuto: las convierte en la pausa entre llamadas,
    # que es lo que de verdad respeta la cuota del servicio (2 por minuto = 30 s de espera).
    monkeypatch.setattr("google.genai.Client", ClienteFalso)
    configuracion = config(
        extractor="gemini", gemini_api_key="llave", llm_batch_size=25, llm_max_rpm=2
    )
    extractor = construir_extractor(configuracion, CATALOGO)
    assert extractor.tamano_lote == 25
    assert extractor._pausa == 30


def test_sin_limite_de_peticiones_no_se_divide_por_cero(monkeypatch) -> None:
    monkeypatch.setattr("google.genai.Client", ClienteFalso)
    configuracion = config(extractor="gemini", gemini_api_key="llave", llm_max_rpm=0)
    assert construir_extractor(configuracion, CATALOGO)._pausa == 0.0


# --------------------------------------------------------------------------------------
# _extractor_de: la procedencia que se guarda en cada fila
# --------------------------------------------------------------------------------------


class ExtractorConRespaldo:
    nombre = "gemini"

    def __init__(self, resueltas: tuple[str, ...]) -> None:
        self.resueltas_por_respaldo = resueltas


def test_una_conversacion_normal_la_firma_el_extractor_configurado() -> None:
    assert _extractor_de(ExtractorConRespaldo(()), "CV-1") == "gemini"


def test_una_conversacion_que_resolvio_el_respaldo_se_firma_como_reglas() -> None:
    # La fila debe decir la verdad: esa la resolvieron las reglas, no el modelo.
    assert _extractor_de(ExtractorConRespaldo(("CV-2",)), "CV-2") == "reglas"


def test_un_extractor_sin_respaldo_firma_con_su_nombre() -> None:
    reglas = ExtractorReglas(["Bajaj"])
    assert _extractor_de(reglas, "CV-1") == reglas.nombre
