"""Comprobación de la evidencia que cita el extractor (TRD 8.1).

El extractor devuelve, por campo, un fragmento del chat que lo justifica. Un LLM puede inventarlo,
copiar lo que dijo el asesor o traerlo de otra conversación del mismo lote, y la app lo mostraría
como cita textual. Aquí se comprueba que el fragmento esté de verdad en la conversación, y que sea
del cliente cuando el campo habla de lo que dijo el cliente.

Solo usa la biblioteca estándar: la app la importa y no instala las dependencias del pipeline.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# «El cliente no respondió» no se puede probar con palabras del cliente: la evidencia natural es el
# último mensaje del asesor que quedó sin respuesta. Es el único campo que puede citar al asesor.
CAMPOS_QUE_CITAN_AL_ASESOR = frozenset({"cliente_respondio"})

# El modelo recibe cada mensaje como «emisor [hora]: texto» (`base.formatear`) y a veces copia
# la línea entera. Ese encabezado no es parte de la cita.
ENCABEZADO = re.compile(r"^\s*(cliente|asesor)\s*\[[^\]]*\]\s*:\s*", re.IGNORECASE)

# Parecido mínimo (0 a 1) para aceptar una cita copiada con una errata. Deja pasar una o dos letras
# cambiadas, no una paráfrasis. Es a propósito: la app muestra la evidencia como cita textual, y
# decidir si otras palabras dicen lo mismo es un juicio de significado, el mismo que hace el modelo
# y que aquí se quiere comprobar. Rechazar una paráfrasis cuesta poco (el campo pasa a desconocido);
# aceptar una cita inventada haría pasar por dicho algo que el cliente no dijo.
SIMILITUD_MINIMA = 0.9


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y con la puntuación y los espacios reducidos a un espacio."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c)
    )
    return re.sub(r"[^\w$]+", " ", sin_tildes).strip()


def campos_sin_respaldo(evidencia: dict[str, str] | None, mensajes: list[dict]) -> list[str]:
    """Campos cuyo fragmento no aparece donde debería, en los mensajes de esa conversación.

    `mensajes` son los de la conversación, con `emisor` y `texto`. Se compara con los mensajes
    seguidos, porque un fragmento puede cruzar dos. Un fragmento vacío no cita nada y no se cuenta.
    """

    def seguidos(emisores: set[str] | None) -> str:
        return " ".join(
            normalizar(m["texto"]) for m in mensajes if emisores is None or m["emisor"] in emisores
        )

    del_cliente, todos = seguidos({"cliente"}), seguidos(None)
    faltan = []
    for campo, fragmento in (evidencia or {}).items():
        cita = normalizar(ENCABEZADO.sub("", fragmento or ""))
        donde = todos if campo in CAMPOS_QUE_CITAN_AL_ASESOR else del_cliente
        if cita and not aparece(cita, donde):
            faltan.append(campo)
    return faltan


def aparece(cita: str, texto: str) -> bool:
    """La cita está en el texto, literal o con una errata de copia.

    El modelo a veces copia con un error («não tienen», «visitiar»): eso no vuelve falsa la cita.
    Se compara contra cada tramo del texto con el mismo número de palabras y se acepta desde
    `SIMILITUD_MINIMA`; un texto inventado o dicho por otra persona queda muy por debajo.
    """
    if cita in texto:
        return True
    palabras, largo = texto.split(), len(cita.split())
    return any(
        SequenceMatcher(None, cita, " ".join(palabras[i : i + largo])).ratio() >= SIMILITUD_MINIMA
        for i in range(max(1, len(palabras) - largo + 1))
    )
