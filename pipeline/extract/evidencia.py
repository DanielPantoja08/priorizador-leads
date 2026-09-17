"""Comprobación de la evidencia que cita el extractor (TRD 8.1).

El extractor devuelve, por campo, un fragmento del chat que lo justifica. Un LLM puede inventarlo,
copiar lo que dijo el asesor o traerlo de otra conversación del mismo lote, y la app lo mostraría
como cita textual. Aquí se comprueba que el fragmento esté de verdad en lo que escribió el cliente.

Solo usa la biblioteca estándar: la app la importa y no instala las dependencias del pipeline.
"""

from __future__ import annotations

import re
import unicodedata


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y con la puntuación y los espacios reducidos a un espacio."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c)
    )
    return re.sub(r"[^\w$]+", " ", sin_tildes).strip()


def campos_sin_respaldo(evidencia: dict[str, str] | None, textos_cliente: list[str]) -> list[str]:
    """Campos cuyo fragmento no aparece en los mensajes del cliente de esa conversación.

    Se compara con los mensajes seguidos, porque un fragmento puede cruzar dos mensajes. Un
    fragmento vacío no cita nada y no se cuenta.
    """
    seguidos = " ".join(normalizar(t) for t in textos_cliente)
    return [
        campo
        for campo, fragmento in (evidencia or {}).items()
        if normalizar(fragmento or "") and normalizar(fragmento) not in seguidos
    ]
