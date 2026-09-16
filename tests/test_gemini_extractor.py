"""Pruebas del extractor con Gemini (TRD 14): lotes, IDs faltantes, respuesta inválida,
reintentos, caché y respaldo por reglas. **Todo simulado: ninguna prueba llama al servicio.**
"""

from __future__ import annotations

import json

import pytest
from google.genai import errors

from pipeline.extract.base import extraer_con_cache
from pipeline.extract.gemini import ExtractorGemini, es_reintentable
from pipeline.extract.rules import ExtractorReglas
from pipeline.extract.schema import Extraccion

MARCAS = ["AKT", "Bajaj", "Honda", "Suzuki"]


def conversacion(cid: str, texto: str = "Hola, me interesa la Honda CB 190R") -> dict:
    return {
        "conversacion_id": cid,
        "lead_id": f"LEAD-{cid}",
        "mensajes": [
            {"emisor": "cliente", "hora": "10:00", "texto": texto},
            {"emisor": "asesor", "hora": "10:01", "texto": "Con mucho gusto"},
            {"emisor": "cliente", "hora": "10:02", "texto": "Listo, sepáremela"},
        ],
    }


def respuesta_de(*ids: str) -> str:
    """JSON como el que devuelve el modelo, con una entrada por conversación."""
    return json.dumps(
        [
            {
                "conversacion_id": cid,
                "modelo_texto": "Honda CB 190R",
                "cuota_inicial_cop": 2_000_000,
                "menciona_cuota": "SI",
                "forma_pago": "credito",
                "intencion": "alta",
                "objecion": "ninguna",
                "pidio_cita": True,
                "pidio_cotizacion": False,
                "cliente_respondio": True,
                "evidencia": [{"campo": "pidio_cita", "fragmento": "sepáremela"}],
            }
            for cid in ids
        ]
    )


class RespuestaFalsa:
    def __init__(self, texto: str) -> None:
        self.text = texto


class ModelosFalsos:
    """Devuelve una respuesta (o lanza una excepción) por cada llamada, en orden."""

    def __init__(self, guion: list) -> None:
        self.guion = list(guion)
        self.peticiones: list[str] = []

    def generate_content(self, *, model, contents, config):
        self.peticiones.append(contents)
        siguiente = self.guion.pop(0) if self.guion else respuesta_de()
        if isinstance(siguiente, BaseException):
            raise siguiente
        return RespuestaFalsa(siguiente)


class ClienteFalso:
    def __init__(self, guion: list) -> None:
        self.models = ModelosFalsos(guion)


def construir(guion: list, **kwargs) -> ExtractorGemini:
    """Extractor con el reloj y la espera simulados: las pruebas no duermen."""
    return ExtractorGemini(
        cliente=ClienteFalso(guion),
        modelo="gemini-simulado",
        respaldo=ExtractorReglas(MARCAS),
        dormir=lambda _s: None,
        reloj=lambda: 0.0,
        **kwargs,
    )


def error_servidor() -> errors.ServerError:
    return errors.ServerError(503, {"error": {"message": "servicio no disponible"}})


def error_cuota() -> errors.ClientError:
    return errors.ClientError(429, {"error": {"message": "demasiadas peticiones"}})


def test_divide_en_lotes() -> None:
    convs = [conversacion(f"CONV-{i}") for i in range(5)]
    extractor = construir(
        [
            respuesta_de("CONV-0", "CONV-1"),
            respuesta_de("CONV-2", "CONV-3"),
            respuesta_de("CONV-4"),
        ],
        tamano_lote=2,
    )
    resultado = extractor.extraer(convs)
    assert len(resultado) == 5
    assert extractor.llamadas == 3
    assert extractor.uso_respaldo is False


def test_conserva_el_orden_de_entrada() -> None:
    convs = [conversacion(f"CONV-{i}") for i in range(3)]
    extractor = construir([respuesta_de("CONV-2", "CONV-0", "CONV-1")])
    assert [e.conversacion_id for e in extractor.extraer(convs)] == ["CONV-0", "CONV-1", "CONV-2"]


def test_id_faltante_se_reintenta_solo() -> None:
    convs = [conversacion("CONV-A"), conversacion("CONV-B")]
    # El lote devuelve solo A; B se pide de nuevo por separado.
    extractor = construir([respuesta_de("CONV-A"), respuesta_de("CONV-B")])
    resultado = extractor.extraer(convs)
    assert extractor.llamadas == 2
    assert extractor.uso_respaldo is False
    assert [e.conversacion_id for e in resultado] == ["CONV-A", "CONV-B"]


def test_ignora_ids_que_no_se_pidieron() -> None:
    extractor = construir([respuesta_de("CONV-A", "CONV-INTRUSA")])
    resultado = extractor.extraer([conversacion("CONV-A")])
    assert [e.conversacion_id for e in resultado] == ["CONV-A"]


def test_respuesta_invalida_cae_a_reglas() -> None:
    extractor = construir(["esto no es json", "tampoco es json"])
    resultado = extractor.extraer([conversacion("CONV-A")])
    assert extractor.uso_respaldo is True
    assert extractor.errores == 2  # el lote y el reintento individual
    assert resultado[0].pidio_cita is True  # lo resolvieron las reglas


def test_reintenta_ante_error_de_servidor() -> None:
    extractor = construir([error_servidor(), error_servidor(), respuesta_de("CONV-A")])
    resultado = extractor.extraer([conversacion("CONV-A")])
    assert extractor.llamadas == 3
    assert extractor.errores == 0
    assert extractor.uso_respaldo is False
    assert resultado[0].cuota_inicial_cop == 2_000_000


def test_agota_reintentos_y_usa_respaldo() -> None:
    extractor = construir([error_servidor()] * 12)
    resultado = extractor.extraer([conversacion("CONV-A")])
    assert extractor.uso_respaldo is True
    assert resultado[0].conversacion_id == "CONV-A"


def test_registra_que_conversacion_resolvio_el_respaldo() -> None:
    # El lote responde solo por A; B falla incluso en su reintento individual.
    convs = [conversacion("CONV-A"), conversacion("CONV-B")]
    extractor = construir([respuesta_de("CONV-A"), "no es json"], tamano_lote=2)
    extractor.extraer(convs)
    assert extractor.resueltas_por_respaldo == {"CONV-B"}
    assert extractor.extractor_de("CONV-A") == "gemini"
    assert extractor.extractor_de("CONV-B") == "reglas"


def test_no_reintenta_errores_del_cliente() -> None:
    # Un 400 es culpa de la petición: reintentarlo solo gasta cuota.
    extractor = construir(
        [errors.ClientError(400, {"error": {"message": "petición inválida"}})] * 4
    )
    extractor.extraer([conversacion("CONV-A")])
    assert extractor.llamadas == 2  # el lote y el reintento individual, sin repetir
    assert extractor.uso_respaldo is True


@pytest.mark.parametrize(
    ("error", "esperado"),
    [
        (error_servidor(), True),
        (error_cuota(), True),
        (errors.ClientError(400, {"error": {}}), False),
    ],
)
def test_clasificacion_de_errores(error: BaseException, esperado: bool) -> None:
    assert es_reintentable(error) is esperado


def test_el_prompt_incluye_las_conversaciones() -> None:
    extractor = construir([respuesta_de("CONV-A")])
    extractor.extraer([conversacion("CONV-A")])
    enviado = extractor.cliente.models.peticiones[0]
    assert "CONV-A" in enviado
    assert "palos" in enviado  # las reglas de jerga viajan en el prompt


# ---------------------------------------------------------------------------
# Caché por hash de contenido
# ---------------------------------------------------------------------------
def test_la_cache_evita_la_llamada() -> None:
    conv = conversacion("CONV-A")
    guardada = Extraccion(conversacion_id="CONV-VIEJA", intencion="alta")
    from pipeline.ingest import hash_mensajes

    cache = {hash_mensajes(conv["mensajes"]): guardada}
    extractor = construir([])
    resultado, nuevas = extraer_con_cache([conv], extractor, cache)
    assert nuevas == 0
    assert extractor.llamadas == 0
    # La extracción reusada queda con el id de la conversación actual.
    assert resultado[0].conversacion_id == "CONV-A"
    assert resultado[0].intencion == "alta"


def test_conversaciones_identicas_se_calculan_una_vez() -> None:
    convs = [conversacion("CONV-A"), conversacion("CONV-B")]  # mismo contenido, distinto id
    extractor = construir([respuesta_de("CONV-A")])
    resultado, nuevas = extraer_con_cache(convs, extractor, {})
    assert nuevas == 1
    assert extractor.llamadas == 1
    assert [e.conversacion_id for e in resultado] == ["CONV-A", "CONV-B"]


def test_sin_cache_se_calculan_todas() -> None:
    convs = [
        conversacion("CONV-A"),
        conversacion("CONV-B", texto="Hola, me interesa la AKT NKD 125"),
    ]
    extractor = construir([respuesta_de("CONV-A", "CONV-B")])
    _, nuevas = extraer_con_cache(convs, extractor, {})
    assert nuevas == 2
