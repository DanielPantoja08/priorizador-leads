"""Etapa de extracción dentro del pipeline (TRD 8).

Une las piezas: elige el extractor según la configuración, reusa lo que ya está en la caché,
valida cada resultado contra el catálogo, lo guarda y lo consolida por lead.
"""

from __future__ import annotations

import pandas as pd
import psycopg

from pipeline import load
from pipeline.catalog_match import Catalogo
from pipeline.config import Config
from pipeline.extract.base import Extractor, extraer_con_cache
from pipeline.extract.consolidar import Senales, consolidar
from pipeline.extract.gemini import ExtractorGemini
from pipeline.extract.rules import ExtractorReglas
from pipeline.extract.schema import validar
from pipeline.ingest import hash_mensajes
from pipeline.quality import ColectorCalidad

ARCHIVO_CONVERSACIONES = "conversaciones.json"
MODELO_GEMINI_POR_DEFECTO = "gemini-2.5-flash"


def construir_extractor(config: Config, catalogo: Catalogo) -> Extractor:
    """Devuelve el extractor configurado. El de reglas es siempre el respaldo del de Gemini."""
    marcas = sorted(set(catalogo.modelos["marca"]))
    reglas = ExtractorReglas(marcas)
    if config.extractor == "reglas":
        return reglas
    if not config.gemini_api_key:
        raise RuntimeError(
            "EXTRACTOR=gemini necesita GEMINI_API_KEY en .env. "
            "Use EXTRACTOR=reglas mientras no tenga la llave."
        )
    from google import genai  # se importa aquí para no exigir credenciales al usar reglas

    return ExtractorGemini(
        cliente=genai.Client(api_key=config.gemini_api_key),
        modelo=config.gemini_model or MODELO_GEMINI_POR_DEFECTO,
        respaldo=reglas,
        tamano_lote=config.llm_batch_size,
        max_rpm=config.llm_max_rpm,
    )


def _extractor_de(extractor: Extractor, conversacion_id: str) -> str:
    """Nombre del extractor que resolvió la conversación (el de reglas si hubo respaldo)."""
    return (
        "reglas"
        if conversacion_id in getattr(extractor, "resueltas_por_respaldo", ())
        else extractor.nombre
    )


def ejecutar(
    conn: psycopg.Connection,
    config: Config,
    conversaciones: list[dict],
    leads: pd.DataFrame,
    catalogo: Catalogo,
    colector: ColectorCalidad,
) -> tuple[dict[str, Senales], dict]:
    """Extrae, valida, guarda y consolida. Devuelve las señales por lead y los conteos."""
    extractor = construir_extractor(config, catalogo)
    cache = load.extracciones_cacheadas(conn, extractor.nombre, extractor.version)
    extracciones, nuevas = extraer_con_cache(conversaciones, extractor, cache)

    precios = dict(zip(catalogo.modelos["sku"], catalogo.modelos["precio_lista"], strict=True))
    empresas = dict(zip(leads["lead_id"], leads["empresa_id"], strict=True))
    modelo_llm = getattr(extractor, "modelo", None)

    filas, por_conversacion = [], {}
    for conversacion, extraccion in zip(conversaciones, extracciones, strict=True):
        conversacion_id = conversacion["conversacion_id"]
        empresa = empresas.get(conversacion["lead_id"])  # None en las huérfanas
        sku = catalogo.resolver(extraccion.modelo_texto).sku

        # La validación se aplica en cada corrida, nunca se guarda ya aplicada: así los problemas
        # de calidad salen iguales se use o no la caché, y la base conserva lo que dijo el extractor.
        validada, correcciones = validar(extraccion, precios.get(sku))
        for tipo in correcciones:
            colector.registrar(ARCHIVO_CONVERSACIONES, conversacion_id, "cuota_inicial_cop", tipo, extraccion.cuota_inicial_cop, "valor corregido por la validación", empresa)  # fmt: skip

        por_conversacion[conversacion_id] = validada
        filas.append({
            "conversacion_id": conversacion_id,
            "empresa_id": empresa,
            "hash_contenido": hash_mensajes(conversacion["mensajes"]),
            "extractor": _extractor_de(extractor, conversacion_id),
            "modelo_llm": modelo_llm,
            "prompt_version": extractor.version,
            "modelo_texto": extraccion.modelo_texto,
            "sku_interes": sku,
            "cuota_inicial_cop": extraccion.cuota_inicial_cop,
            "menciona_cuota": extraccion.menciona_cuota,
            "forma_pago": extraccion.forma_pago,
            "intencion": extraccion.intencion,
            "objecion": extraccion.objecion,
            "pidio_cita": extraccion.pidio_cita,
            "pidio_cotizacion": extraccion.pidio_cotizacion,
            "cliente_respondio": extraccion.cliente_respondio,
            "evidencia": extraccion.evidencia,
        })  # fmt: skip

    guardadas = load.cargar_extracciones(conn, filas)
    senales = consolidar(leads, conversaciones, por_conversacion)
    conteos = {
        "extraccion": guardadas,
        "extraccion_calculadas": nuevas,
        "extraccion_reusadas": len(conversaciones) - nuevas,
        "extraccion_respaldo": len(getattr(extractor, "resueltas_por_respaldo", ())),
        "leads_con_senales": len(senales),
        # Métricas del LLM; con el extractor por reglas quedan en cero.
        "llamadas_llm": getattr(extractor, "llamadas", 0),
        "errores_llm": getattr(extractor, "errores", 0),
    }
    return senales, conteos
