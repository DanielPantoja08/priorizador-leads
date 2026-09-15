"""Utilidades compartidas del EDA: rutas, carga de insumos, intervalos y clasificación de formatos.

Las reglas de normalización (teléfono y fechas, TRD 6 y 6.1) se importan de `pipeline/normalize.py`:
hay una sola implementación, y el EDA mide exactamente lo que después hace el pipeline.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin interfaz gráfica: las figuras solo se guardan en disco

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

# Se reexportan para que los módulos del EDA las usen desde aquí.
from pipeline.normalize import (  # noqa: E402
    clave_texto,
    lecturas_fecha,
    normalizar_telefono,
    resolver_fecha,
)

__all__ = [
    "clave_texto",
    "lecturas_fecha",
    "normalizar_telefono",
    "resolver_fecha",
]

RAIZ = Path(__file__).resolve().parent.parent
DIR_RAW = RAIZ / "data" / "raw"
DIR_DOCS = RAIZ / "docs"
DIR_IMG = DIR_DOCS / "img" / "eda"


# ---------------------------------------------------------------------------
# Carga de insumos (solo lectura)
# ---------------------------------------------------------------------------
def cargar_csv(nombre: str) -> pd.DataFrame:
    """Lee un CSV de data/raw como texto para no perder los formatos originales (vacíos -> NaN)."""
    return pd.read_csv(DIR_RAW / nombre, dtype="str", encoding="utf-8")


def cargar_conversaciones() -> list[dict]:
    """Lee conversaciones.json tal como viene."""
    with open(DIR_RAW / "conversaciones.json", encoding="utf-8") as archivo:
        return json.load(archivo)


# ---------------------------------------------------------------------------
# Estadística
# ---------------------------------------------------------------------------
def wilson(exitos: int, n: int, z: float = 1.96) -> tuple[float, float, float] | None:
    """Tasa e intervalo de confianza de Wilson (95 % por defecto). Devuelve None si n = 0."""
    if n == 0:
        return None
    p = exitos / n
    denominador = 1 + z**2 / n
    centro = (p + z**2 / (2 * n)) / denominador
    margen = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominador
    return p, centro - margen, centro + margen


def pct(valor: float | None, decimales: int = 1) -> str:
    """Formatea una proporción como porcentaje con coma decimal: 0.0975 -> '9,8 %'."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "—"
    return f"{valor * 100:.{decimales}f}".replace(".", ",") + " %"


def num(valor: float, decimales: int = 3) -> str:
    """Formatea un número con coma decimal."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def miles(valor: int) -> str:
    """Formatea un entero con punto de miles: 2200 -> '2.200'."""
    return f"{valor:,}".replace(",", ".")


def z_dos_proporciones(e1: int, n1: int, e2: int, n2: int) -> float:
    """Valor p bilateral de la prueba z de diferencia de dos proporciones."""
    if min(n1, n2) == 0:
        return float("nan")
    p = (e1 + e2) / (n1 + n2)
    error = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if error == 0:
        return 1.0
    z = abs(e1 / n1 - e2 / n2) / error
    return math.erfc(z / math.sqrt(2))


def tabla_md(encabezados: list[str], filas: list[list]) -> str:
    """Construye una tabla Markdown. Las barras verticales del contenido se escapan."""

    def celda(valor) -> str:
        return str(valor).replace("|", "\\|").replace("\n", " ")

    lineas = [
        "| " + " | ".join(encabezados) + " |",
        "|" + "|".join("---" for _ in encabezados) + "|",
    ]
    lineas += ["| " + " | ".join(celda(v) for v in fila) + " |" for fila in filas]
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Formatos de escritura (solo para medir cuántas variantes traen los datos)
# ---------------------------------------------------------------------------
def forma_telefono(texto: str) -> str:
    """Patrón de escritura del teléfono (dígitos -> 9) para contar formatos distintos."""
    return re.sub(r"\d", "9", str(texto))


# Patrones de los cuatro formatos de fecha, solo para clasificarlos y contarlos.
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$")
_DIA = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
_BARRAS = re.compile(r"^(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2})$")


def formato_fecha(texto: str | float | None) -> str:
    """Clasifica el texto: iso_espacio, iso_t, dd-mm-yyyy, barras, vacio o desconocido."""
    if texto is None or (isinstance(texto, float) and math.isnan(texto)) or not str(texto).strip():
        return "vacio"
    t = str(texto).strip()
    if _ISO.match(t):
        return "iso_t" if "T" in t else "iso_espacio"
    if _DIA.match(t):
        return "dd-mm-yyyy"
    if _BARRAS.match(t):
        return "barras"
    return "desconocido"


def clase_barras(texto: str) -> str:
    """Para fechas con barras: 'ddmm' o 'mmdd' si un componente > 12, 'igual' si x = y, si no 'ambigua'."""
    x, y = (int(p) for p in str(texto).strip()[:5].split("/"))
    if x > 12:
        return "ddmm"
    if y > 12:
        return "mmdd"
    return "igual" if x == y else "ambigua"


# ---------------------------------------------------------------------------
# Figuras
# ---------------------------------------------------------------------------
def guardar_figura(fig: plt.Figure, nombre: str) -> str:
    """Guarda la figura en docs/img/eda sin metadatos variables y devuelve la ruta relativa a docs/."""
    DIR_IMG.mkdir(parents=True, exist_ok=True)
    ruta = DIR_IMG / nombre
    fig.savefig(ruta, dpi=110, bbox_inches="tight", metadata={"Software": None})
    plt.close(fig)
    return f"img/eda/{nombre}"
