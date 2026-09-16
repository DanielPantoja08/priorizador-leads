"""Evalúa los extractores contra el conjunto de referencia (TRD 8.5).

**Solo se evalúan los registros revisados por una persona** (`"revisado": true`). El borrador que
propone la IA no cuenta como conjunto de referencia y nunca se presenta como etiquetado manual.

Uso: `uv run python -m pipeline eval`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pipeline.extract.rules import ExtractorReglas  # noqa: E402
from pipeline.extract.schema import CAMPOS_EVALUADOS, Extraccion  # noqa: E402
from pipeline.ingest import leer_conversaciones, leer_csv  # noqa: E402
from pipeline.normalize import clave_texto  # noqa: E402

RUTA_GOLD = RAIZ / "evaluation" / "gold_40.json"
RUTA_BORRADOR = RAIZ / "evaluation" / "gold_40_borrador.json"

# La cuota se da por acertada si cae dentro de este margen del valor de referencia (TRD 8.5).
TOLERANCIA_CUOTA = 0.05


def cargar_referencia(ruta: Path) -> list[dict]:
    """Registros revisados del conjunto de referencia. Lanza un error si no hay ninguno."""
    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe {ruta.name}. Una persona debe revisar {RUTA_BORRADOR.name} "
            'y guardar el resultado con "revisado": true.'
        )
    registros = json.loads(ruta.read_text(encoding="utf-8"))
    revisados = [r for r in registros if r.get("revisado") is True]
    if not revisados:
        raise ValueError(
            f"{ruta.name} no tiene registros revisados. La evaluación solo usa los revisados."
        )
    return revisados


def coincide(campo: str, esperado: object, obtenido: object) -> bool:
    """Compara un campo según su tipo: la cuota con tolerancia y el modelo sin tildes ni mayúsculas."""
    if campo == "cuota_inicial_cop":
        if esperado is None or obtenido is None:
            return esperado == obtenido
        if esperado == 0:
            return obtenido == 0
        return abs(obtenido - esperado) <= TOLERANCIA_CUOTA * abs(esperado)
    if campo == "modelo_texto":
        return clave_texto(esperado) == clave_texto(obtenido)
    return esperado == obtenido


def evaluar(
    referencia: list[dict], extracciones: dict[str, Extraccion]
) -> dict[str, tuple[int, int]]:
    """Aciertos y total por campo, solo sobre los registros que el extractor resolvió."""
    marcador: dict[str, tuple[int, int]] = {}
    for campo in CAMPOS_EVALUADOS:
        aciertos = total = 0
        for registro in referencia:
            extraccion = extracciones.get(registro["conversacion_id"])
            if extraccion is None or campo not in registro:
                continue
            total += 1
            aciertos += coincide(campo, registro[campo], getattr(extraccion, campo))
        marcador[campo] = (aciertos, total)
    return marcador


def tabla_markdown(marcadores: dict[str, dict[str, tuple[int, int]]]) -> str:
    """Tabla de exactitud por campo, con una columna por extractor evaluado."""
    extractores = list(marcadores)
    lineas = [
        "| Campo | " + " | ".join(extractores) + " |",
        "|---|" + "|".join("---" for _ in extractores) + "|",
    ]
    for campo in CAMPOS_EVALUADOS:
        celdas = []
        for extractor in extractores:
            aciertos, total = marcadores[extractor][campo]
            porcentaje = f"{aciertos / total * 100:.1f}".replace(".", ",") if total else "—"
            celdas.append(f"{porcentaje} % ({aciertos}/{total})")
        lineas.append(f"| `{campo}` | " + " | ".join(celdas) + " |")

    # Promedio simple de los campos con datos, como cifra de resumen.
    resumen = []
    for extractor in extractores:
        pares = [v for v in marcadores[extractor].values() if v[1]]
        promedio = sum(a / t for a, t in pares) / len(pares) * 100 if pares else 0
        resumen.append(f"**{promedio:.1f}".replace(".", ",") + " %**")
    lineas.append("| **Promedio** | " + " | ".join(resumen) + " |")
    return "\n".join(lineas)


def main(ruta_gold: Path = RUTA_GOLD) -> int:
    """Corre la evaluación y escribe la tabla en la salida estándar."""
    try:
        referencia = cargar_referencia(ruta_gold)
    except (FileNotFoundError, ValueError) as error:
        print(f"No se puede evaluar: {error}", file=sys.stderr)
        return 2

    conversaciones = {c["conversacion_id"]: c for c in leer_conversaciones()}
    seleccionadas = [
        conversaciones[r["conversacion_id"]]
        for r in referencia
        if r["conversacion_id"] in conversaciones
    ]
    marcas = sorted(set(leer_csv("catalogo_motos.csv")["marca"].str.strip()))

    # El extractor por reglas es la línea base; no necesita red ni credenciales.
    reglas = ExtractorReglas(marcas)
    marcadores = {
        "reglas": evaluar(
            referencia,
            {e.conversacion_id: e for e in reglas.extraer(seleccionadas)},
        )
    }

    print(f"Conjunto de referencia: {len(referencia)} conversaciones revisadas\n")
    print(tabla_markdown(marcadores))
    return 0


if __name__ == "__main__":
    sys.exit(main())
