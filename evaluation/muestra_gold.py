"""Selecciona la muestra del conjunto de referencia (TRD 8.5).

La muestra es **estratificada y determinista**: cubre los casos difíciles (cambio de modelo,
jerga de montos, "0 millones", conversaciones sin respuesta y cada tipo de objeción) y siempre
devuelve las mismas 40 conversaciones, así que el conjunto es reproducible.

Este script **no etiqueta**: solo elige y vuelca los textos para que se propongan las etiquetas.
Uso: `uv run python evaluation/muestra_gold.py`
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from pipeline.extract.base import mensajes_de  # noqa: E402
from pipeline.ingest import leer_conversaciones  # noqa: E402

TOTAL = 40
SALIDA = RAIZ / "evaluation" / "gold_40_muestra.json"

# Un estrato por dificultad. El orden importa: los casos difíciles se llenan primero.
ESTRATOS: dict[str, re.Pattern[str] | None] = {
    "jerga_palos": re.compile(r"\bpalos?\b", re.I),
    "jerga_millonzitos": re.compile(r"millonzitos?", re.I),
    "monto_pegado_mil": re.compile(r"\d+mil\b", re.I),
    "monto_en_pesos": re.compile(r"\$\s?\d{1,3}(?:\.\d{3})+"),
    "cero_inicial": re.compile(
        r"\b0\s*(millones|palos|millonzitos)\b|no tengo.{0,20}inicial", re.I
    ),
    "objecion_centrales": re.compile(r"centrales|datacr[eé]dito", re.I),
    "objecion_tasa": re.compile(r"\btasa\b|inter[eé]s.{0,15}car|cu[aá]nto queda la cuota", re.I),
    "objecion_usada": re.compile(r"\busada?s?\b", re.I),
    "objecion_entrega": re.compile(r"demora la entrega|necesito la moto ya", re.I),
    "objecion_familia": re.compile(r"hablo con mi|consultar en la casa", re.I),
    "objecion_comparando": re.compile(r"comparando|otra marca|ofreciendo otra", re.I),
    "objecion_precio": re.compile(
        r"m[aá]s econ[oó]mic|presupuesto|muy costosa|inicial est[aá] muy alta", re.I
    ),
    "solo_averiguando": re.compile(r"solo estaba mirando|por curiosidad", re.I),
    "pidio_cita": re.compile(r"visit|sep[aá]rem|voy en camino|voy saliendo", re.I),
    "contado": re.compile(r"contado", re.I),
}

# Cuántas conversaciones se toman de cada estrato antes de completar con el resto.
POR_ESTRATO = 2


def cambia_de_modelo(textos: list[str], marcas: list[str]) -> bool:
    """El cliente nombra dos modelos distintos a lo largo de la conversación."""
    patron = re.compile(rf"\b({'|'.join(marcas)})\b[\w\s.\-]{{0,20}}", re.I)
    vistos = []
    for texto in textos:
        for hallazgo in patron.finditer(texto):
            limpio = " ".join(hallazgo.group(0).split())
            if limpio not in vistos:
                vistos.append(limpio)
    return len(vistos) >= 2


def seleccionar(conversaciones: list[dict], marcas: list[str]) -> list[dict]:
    """Devuelve las 40 conversaciones de la muestra, con el estrato que las hizo entrar."""
    ordenadas = sorted(conversaciones, key=lambda c: c["conversacion_id"])
    elegidas: dict[str, str] = {}  # conversacion_id -> estrato

    def agregar(conversacion: dict, estrato: str) -> None:
        elegidas.setdefault(conversacion["conversacion_id"], estrato)

    # 1) Casos que no dependen del texto: silencio del cliente y cambio de modelo.
    for conversacion in ordenadas:
        textos = mensajes_de(conversacion)
        if len(textos) <= 1 and sum(e == "sin_respuesta" for e in elegidas.values()) < POR_ESTRATO:
            agregar(conversacion, "sin_respuesta")
    for conversacion in ordenadas:
        textos = mensajes_de(conversacion)
        if (
            cambia_de_modelo(textos, marcas)
            and sum(e == "cambio_de_modelo" for e in elegidas.values()) < POR_ESTRATO
        ):
            agregar(conversacion, "cambio_de_modelo")

    # 2) Un par de conversaciones por cada estrato de texto.
    for estrato, patron in ESTRATOS.items():
        tomadas = 0
        for conversacion in ordenadas:
            if tomadas >= POR_ESTRATO:
                break
            if conversacion["conversacion_id"] in elegidas:
                continue
            if patron and any(patron.search(t) for t in mensajes_de(conversacion)):
                agregar(conversacion, estrato)
                tomadas += 1

    # 3) Se completa con conversaciones corrientes, para no evaluar solo casos difíciles.
    for conversacion in ordenadas:
        if len(elegidas) >= TOTAL:
            break
        agregar(conversacion, "corriente")

    por_id = {c["conversacion_id"]: c for c in conversaciones}
    return [
        {
            "conversacion_id": cid,
            "lead_id": por_id[cid]["lead_id"],
            "estrato": estrato,
            "mensajes": [
                {"emisor": m.get("emisor"), "texto": m.get("texto")}
                for m in por_id[cid]["mensajes"]
            ],
        }
        for cid, estrato in list(elegidas.items())[:TOTAL]
    ]


def main() -> None:
    from pipeline.ingest import leer_csv

    marcas = sorted(set(leer_csv("catalogo_motos.csv")["marca"].str.strip()))
    muestra = seleccionar(leer_conversaciones(), marcas)
    SALIDA.write_text(json.dumps(muestra, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    conteo: dict[str, int] = {}
    for registro in muestra:
        conteo[registro["estrato"]] = conteo.get(registro["estrato"], 0) + 1
    print(f"{len(muestra)} conversaciones en {SALIDA.relative_to(RAIZ)}")
    for estrato, n in sorted(conteo.items()):
        print(f"  {estrato}: {n}")


if __name__ == "__main__":
    main()
