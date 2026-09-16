"""Extractor con Gemini (TRD 8.2): lotes, salida estructurada, reintentos y respaldo por reglas.

El cliente se recibe por parámetro para que las pruebas lo simulen: este módulo nunca abre
una conexión por su cuenta ni las pruebas llaman al servicio real (TRD 14).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from google.genai import errors, types
from pydantic import ValidationError
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from pipeline.extract.base import PROMPT_VERSION, Extractor, formatear
from pipeline.extract.schema import Extraccion, ExtraccionLLM

DIR_PROMPTS = Path(__file__).parent / "prompts"
MAX_INTENTOS = 5


def cargar_prompt(version: str = PROMPT_VERSION) -> str:
    """Lee el prompt versionado. Cambiarlo obliga a subir la versión (TRD 15.2)."""
    return (DIR_PROMPTS / f"extraccion_{version}.md").read_text(encoding="utf-8")


def es_reintentable(error: BaseException) -> bool:
    """Se reintenta ante saturación (429) y errores del servidor (5xx); lo demás no tiene sentido."""
    if isinstance(error, errors.ServerError):
        return True
    return isinstance(error, errors.ClientError) and getattr(error, "code", None) == 429


def _lotes(elementos: list[dict], tamano: int) -> Iterator[list[dict]]:
    for inicio in range(0, len(elementos), tamano):
        yield elementos[inicio : inicio + tamano]


class ExtractorGemini:
    """Pide las señales a Gemini por lotes y cae al extractor por reglas cuando algo falla."""

    nombre = "gemini"

    def __init__(
        self,
        cliente: object,
        modelo: str,
        respaldo: Extractor,
        tamano_lote: int = 10,
        max_rpm: int = 5,
        version: str = PROMPT_VERSION,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cliente = cliente
        self.modelo = modelo
        self.respaldo = respaldo
        self.tamano_lote = max(1, tamano_lote)
        self.version = version
        self._prompt = cargar_prompt(version)
        self._pausa = 60 / max_rpm if max_rpm > 0 else 0.0
        self._dormir = dormir
        self._reloj = reloj
        self._ultima_llamada: float | None = None
        # Métricas de la corrida, que se guardan en `ejecucion` (TRD 13).
        self.llamadas = 0
        self.errores = 0
        self.uso_respaldo = False
        # Conversaciones que terminó resolviendo el extractor por reglas: su fila en la base
        # se guarda con extractor='reglas' (TRD 8.2), no con 'gemini'.
        self.resueltas_por_respaldo: set[str] = set()

    # -- llamada al servicio ------------------------------------------------
    def _esperar_turno(self) -> None:
        """Respeta el límite propio de peticiones por minuto."""
        if self._ultima_llamada is not None:
            restante = self._pausa - (self._reloj() - self._ultima_llamada)
            if restante > 0:
                self._dormir(restante)
        self._ultima_llamada = self._reloj()

    def _generar(self, conversaciones: list[dict]) -> str:
        """Una petición: devuelve el texto JSON de la respuesta."""
        self._esperar_turno()
        self.llamadas += 1
        contenido = (
            self._prompt
            + "\n\n## Conversaciones\n\n"
            + "\n\n".join(formatear(c) for c in conversaciones)
        )
        respuesta = self.cliente.models.generate_content(
            model=self.modelo,
            contents=contenido,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=list[ExtraccionLLM],
                temperature=0,
            ),
        )
        return respuesta.text

    def _pedir(self, conversaciones: list[dict]) -> dict[str, Extraccion]:
        """Pide un lote con reintentos y devuelve solo las extracciones válidas que correspondan."""
        esperados = {c["conversacion_id"] for c in conversaciones}
        for intento in Retrying(
            retry=retry_if_exception(es_reintentable),
            wait=wait_exponential(multiplier=1, max=60),
            stop=stop_after_attempt(MAX_INTENTOS),
            reraise=True,
            sleep=self._dormir,  # inyectado: en las pruebas no se espera de verdad
        ):
            with intento:
                crudo = self._generar(conversaciones)

        obtenidas: dict[str, Extraccion] = {}
        for fila in json.loads(crudo):
            try:
                extraccion = ExtraccionLLM(**fila).a_extraccion()
            except (ValidationError, TypeError):
                continue  # una fila inválida no invalida el lote; se reintenta sola
            if extraccion.conversacion_id in esperados:
                obtenidas[extraccion.conversacion_id] = extraccion
        return obtenidas

    def _intentar(self, conversaciones: list[dict]) -> tuple[dict[str, Extraccion], bool]:
        """Envuelve `_pedir` contando los errores; nunca propaga.

        Devuelve lo obtenido y si la petición en sí falló, que no es lo mismo que volver vacía.
        """
        try:
            return self._pedir(conversaciones), False
        except (errors.APIError, json.JSONDecodeError, ValueError):
            self.errores += 1
            return {}, True

    def extraer(self, conversaciones: list[dict]) -> list[Extraccion]:
        """Una extracción por conversación. Lo que el LLM no resuelva lo resuelven las reglas."""
        obtenidas: dict[str, Extraccion] = {}
        for lote in _lotes(conversaciones, self.tamano_lote):
            del_lote, fallo = self._intentar(lote)
            obtenidas.update(del_lote)
            if fallo:
                # La petición falló entera (cuota agotada, modelo inexistente, respuesta ilegible).
                # Pedir cada conversación por separado repetiría el mismo error y multiplicaría la
                # espera por el tamaño del lote: se deja que las resuelva el respaldo.
                continue
            # La respuesta llegó pero omitió conversaciones: esas sí vale la pena pedirlas solas.
            for conversacion in lote:
                if conversacion["conversacion_id"] not in obtenidas:
                    individual, _ = self._intentar([conversacion])
                    obtenidas.update(individual)

        faltantes = [c for c in conversaciones if c["conversacion_id"] not in obtenidas]
        if faltantes:
            self.uso_respaldo = True
            for conversacion, extraccion in zip(
                faltantes, self.respaldo.extraer(faltantes), strict=True
            ):
                obtenidas[conversacion["conversacion_id"]] = extraccion
                self.resueltas_por_respaldo.add(conversacion["conversacion_id"])

        return [obtenidas[c["conversacion_id"]] for c in conversaciones]

    def extractor_de(self, conversacion_id: str) -> str:
        """Qué extractor resolvió esa conversación; se guarda en la columna `extractor`."""
        if conversacion_id in self.resueltas_por_respaldo:
            return self.respaldo.nombre
        return self.nombre
