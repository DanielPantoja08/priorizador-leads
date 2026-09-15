"""Configuración del pipeline: rutas, constantes de dominio y variables de entorno (TRD 4)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
DIR_RAW = RAIZ / "data" / "raw"

# Los datos de origen se interpretan en hora de Colombia (TRD 5).
ZONA = ZoneInfo("America/Bogota")

# Ventana de datos de los leads actuales (TRD 6.1, paso 2).
VENTANA_INICIO = date(2026, 8, 1)
VENTANA_FIN = date(2026, 9, 30)


@dataclass(frozen=True)
class Config:
    """Valores leídos del entorno (.env en local; secretos en despliegue)."""

    database_url: str
    extractor: str
    gemini_api_key: str | None
    gemini_model: str | None
    llm_batch_size: int
    llm_max_rpm: int
    fecha_corte: date | None
    ventana_dias: int


def _texto(nombre: str) -> str | None:
    valor = os.getenv(nombre, "").strip()
    return valor or None


def cargar_config() -> Config:
    """Lee la configuración. DATABASE_URL es obligatoria; lo demás tiene valores por defecto."""
    load_dotenv(RAIZ / ".env")
    database_url = _texto("DATABASE_URL")
    if database_url is None:
        raise RuntimeError("Falta DATABASE_URL. Copie .env.example a .env y use `supabase status`.")
    extractor = _texto("EXTRACTOR") or "gemini"
    if extractor not in ("gemini", "reglas"):
        raise RuntimeError(f"EXTRACTOR inválido: {extractor}. Use 'gemini' o 'reglas'.")
    fecha = _texto("FECHA_CORTE")
    return Config(
        database_url=database_url,
        extractor=extractor,
        gemini_api_key=_texto("GEMINI_API_KEY"),
        gemini_model=_texto("GEMINI_MODEL"),
        llm_batch_size=int(_texto("LLM_BATCH_SIZE") or 10),
        llm_max_rpm=int(_texto("LLM_MAX_RPM") or 5),
        fecha_corte=date.fromisoformat(fecha) if fecha else None,
        ventana_dias=int(_texto("VENTANA_DIAS") or 30),
    )
