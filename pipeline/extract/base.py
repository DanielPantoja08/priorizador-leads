"""Interfaz común de los extractores y lectura de las conversaciones (TRD 8).

Los dos extractores (reglas y Gemini) reciben las conversaciones tal como vienen de
`conversaciones.json` y devuelven una `Extraccion` por conversación.
"""

from __future__ import annotations

from typing import Protocol

from pipeline.extract.schema import Extraccion
from pipeline.ingest import hash_mensajes

# Versiones que entran en la clave de caché (hash_contenido, extractor, prompt_version).
# Cambiar el prompt o las reglas obliga a subir la versión, lo que invalida la caché (TRD 8.2, 15.2).
PROMPT_VERSION = "v2"
VERSION_REGLAS = "reglas_v2"


def mensajes_de(conversacion: dict, emisor: str = "cliente") -> list[str]:
    """Textos de un emisor, en orden, sin los vacíos."""
    return [
        str(m["texto"]).strip()
        for m in conversacion.get("mensajes", [])
        if m.get("emisor") == emisor and str(m.get("texto") or "").strip()
    ]


def cliente_respondio(conversacion: dict) -> bool:
    """False si el cliente solo escribió una vez: tras su consulta inicial únicamente habla el asesor."""
    return len(mensajes_de(conversacion)) > 1


def formatear(conversacion: dict) -> str:
    """Conversación como texto plano para el prompt, con su identificador y cada turno etiquetado."""
    turnos = [
        f"{m.get('emisor', '?')} [{m.get('hora', '')}]: {str(m.get('texto') or '').strip()}"
        for m in conversacion.get("mensajes", [])
    ]
    return f"### {conversacion['conversacion_id']}\n" + "\n".join(turnos)


def extraer_con_cache(
    conversaciones: list[dict],
    extractor: Extractor,
    cache: dict[str, Extraccion],
) -> tuple[list[Extraccion], int]:
    """Extrae solo lo que no esté en la caché (TRD 8.2).

    `cache` va del `hash_contenido` de la conversación a su extracción ya guardada. Dos
    conversaciones con el mismo contenido comparten resultado, así que se calcula una sola vez.
    Devuelve las extracciones en el orden de entrada y cuántas hubo que calcular.
    """
    resultados: dict[str, Extraccion] = {}
    pendientes: dict[str, dict] = {}  # hash -> conversación representante
    for conversacion in conversaciones:
        huella = hash_mensajes(conversacion["mensajes"])
        if huella in cache:
            resultados[conversacion["conversacion_id"]] = cache[huella].model_copy(
                update={"conversacion_id": conversacion["conversacion_id"]}
            )
        else:
            pendientes.setdefault(huella, conversacion)

    nuevas = {}
    if pendientes:
        calculadas = extractor.extraer(list(pendientes.values()))
        nuevas = dict(zip(pendientes, calculadas, strict=True))

    for conversacion in conversaciones:
        if conversacion["conversacion_id"] in resultados:
            continue
        extraccion = nuevas[hash_mensajes(conversacion["mensajes"])]
        resultados[conversacion["conversacion_id"]] = extraccion.model_copy(
            update={"conversacion_id": conversacion["conversacion_id"]}
        )

    return [resultados[c["conversacion_id"]] for c in conversaciones], len(pendientes)


class Extractor(Protocol):
    """Contrato que cumplen `ExtractorReglas` y `ExtractorGemini`."""

    nombre: str  # 'reglas' o 'gemini'
    version: str  # entra en la clave de caché

    def extraer(self, conversaciones: list[dict]) -> list[Extraccion]:
        """Una extracción por conversación, en el mismo orden que la entrada."""
        ...
