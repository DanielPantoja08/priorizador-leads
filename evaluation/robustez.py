"""Mide qué pasa con cada extractor cuando el cliente dice lo mismo con otras palabras (TRD 8.5).

`eval_extraction` da a las reglas un 99 % sobre el conjunto de referencia, pero ese número tiene
truco: las 677 conversaciones sintéticas repiten un vocabulario cerrado (los 2.610 mensajes de
cliente salen de 97 frases fijas en las que solo cambian el modelo y las cifras), y las reglas se
escribieron mirando ese vocabulario. Una conversación real de WhatsApp no se ve así.

Esta evaluación reescribe cada frase del cliente con `reformulaciones.json` —mismo significado,
otras palabras, el modelo y las cifras intactos— y vuelve a medir los dos extractores contra las
**mismas** etiquetas. Lo que cae es lo que dependía de la redacción exacta.

Dos límites que se declaran siempre con las cifras:

1. Las reformulaciones las propuso la IA; mientras `"revisado"` sea `false`, las cifras son
   preliminares.
2. Son una sola redacción por frase, no una muestra del lenguaje real: miden fragilidad, no la
   exactitud esperada en producción.

Uso: `uv run python -m pipeline eval-robustness [--con-gemini]`
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from evaluation.eval_extraction import (  # noqa: E402
    RUTA_GOLD,
    cargar_referencia,
    evaluar,
    extractor_gemini,
    tabla_markdown,
)
from pipeline.extract.rules import ExtractorReglas  # noqa: E402
from pipeline.ingest import leer_conversaciones, leer_csv  # noqa: E402

RUTA_REFORMULACIONES = RAIZ / "evaluation" / "reformulaciones.json"


def cargar_reformulaciones(ruta: Path = RUTA_REFORMULACIONES) -> tuple[list[dict], bool]:
    """Sustituciones ordenadas de la más larga a la más corta, y si una persona ya las revisó.

    El orden importa: «Esa sí me sirve. Tengo como» tiene que aplicarse antes que «Esa sí me
    sirve. Tengo», o la segunda se comería el comienzo de la primera.
    """
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    sustituciones = sorted(datos["sustituciones"], key=lambda s: len(s["original"]), reverse=True)
    return sustituciones, datos.get("revisado") is True


def reformular(texto: str, sustituciones: list[dict]) -> tuple[str, set[str]]:
    """Aplica las sustituciones sin distinguir mayúsculas. Devuelve el texto y cuáles se usaron."""
    usadas = set()
    for s in sustituciones:
        patron = re.compile(re.escape(s["original"]), re.IGNORECASE)
        # Una función como reemplazo evita que una barra invertida se lea como referencia a grupo.
        texto, veces = patron.subn(lambda _, nueva=s["reformulada"]: nueva, texto)
        if veces:
            usadas.add(s["original"])
    return texto, usadas


def reformular_conversaciones(
    conversaciones: list[dict], sustituciones: list[dict]
) -> tuple[list[dict], set[str], int]:
    """Copia las conversaciones con los mensajes del cliente reescritos.

    Los mensajes del asesor no se tocan: la prueba es sobre cómo escribe el cliente. Devuelve
    también las sustituciones usadas y cuántos mensajes del cliente cambiaron.
    """
    nuevas, usadas, cambiados = [], set(), 0
    for conversacion in conversaciones:
        copia = copy.deepcopy(conversacion)
        for mensaje in copia["mensajes"]:
            if mensaje["emisor"] != "cliente":
                continue
            texto, usadas_aqui = reformular(mensaje["texto"], sustituciones)
            cambiados += texto != mensaje["texto"]
            mensaje["texto"] = texto
            usadas |= usadas_aqui
        nuevas.append(copia)
    return nuevas, usadas, cambiados


def main(con_gemini: bool = False) -> int:
    """Imprime la exactitud por campo antes y después de reformular."""
    try:
        referencia = cargar_referencia(RUTA_GOLD)
    except (FileNotFoundError, ValueError) as error:
        print(f"No se puede evaluar: {error}", file=sys.stderr)
        return 2
    sustituciones, revisado = cargar_reformulaciones()

    por_id = {c["conversacion_id"]: c for c in leer_conversaciones()}
    originales = [
        por_id[r["conversacion_id"]] for r in referencia if r["conversacion_id"] in por_id
    ]
    reformuladas, usadas, cambiados = reformular_conversaciones(originales, sustituciones)
    total_cliente = sum(1 for c in originales for m in c["mensajes"] if m["emisor"] == "cliente")

    # Una sustitución que no se aplica a nada delata una frase mal copiada: mejor fallar que medir
    # con menos reformulaciones de las que se declaran.
    sin_uso = [s["original"] for s in sustituciones if s["original"] not in usadas]
    if sin_uso:
        print(f"Sustituciones que no se aplicaron: {sin_uso}", file=sys.stderr)
        return 2

    marcas = sorted(set(leer_csv("catalogo_motos.csv")["marca"].str.strip()))
    reglas = ExtractorReglas(marcas)
    marcadores = {
        "reglas · original": evaluar(referencia, _por_id(reglas.extraer(originales))),
        "reglas · reformulado": evaluar(referencia, _por_id(reglas.extraer(reformuladas))),
    }

    notas = []
    if con_gemini:
        for etiqueta, lote in (("original", originales), ("reformulado", reformuladas)):
            # Un extractor nuevo por lote, para contar por separado lo que resolvió el respaldo.
            gemini = extractor_gemini(marcas)
            if gemini is None:
                print("Sin GEMINI_API_KEY: se mide solo el extractor por reglas.", file=sys.stderr)
                break
            marcadores[f"gemini · {etiqueta}"] = evaluar(referencia, _por_id(gemini.extraer(lote)))
            if gemini.resueltas_por_respaldo:
                notas.append(
                    f"En «{etiqueta}», {len(gemini.resueltas_por_respaldo)} conversaciones las "
                    "resolvió el respaldo por reglas, no el modelo."
                )

    print("Robustez de la extracción · TRD 8.5\n")
    if not revisado:
        print("**Cifras preliminares:** una persona todavía no revisa las reformulaciones.\n")
    print(
        f"{len(referencia)} conversaciones de referencia · {len(sustituciones)} frases "
        f"reformuladas · {cambiados} de {total_cliente} mensajes del cliente cambiaron\n"
    )
    print(tabla_markdown(marcadores))
    for nota in notas:
        print(f"\n{nota}")
    return 0


def _por_id(extracciones: list) -> dict:
    return {e.conversacion_id: e for e in extracciones}


if __name__ == "__main__":
    sys.exit(main(con_gemini="--con-gemini" in sys.argv))
