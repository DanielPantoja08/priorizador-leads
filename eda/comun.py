"""Utilidades compartidas del EDA: rutas, carga de insumos, intervalos y normalizaciones de medición.

Las normalizaciones de este módulo existen solo para MEDIR la calidad de los datos. Siguen las reglas de
las secciones 6 y 6.1 del TRD; la implementación definitiva vive en `pipeline/normalize.py` (Fase B).
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin interfaz gráfica: las figuras solo se guardan en disco

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
DIR_RAW = RAIZ / "data" / "raw"
DIR_DOCS = RAIZ / "docs"
DIR_IMG = DIR_DOCS / "img" / "eda"

# Ventana de datos de los leads actuales (TRD 6.1, paso 2).
VENTANA_INICIO = date(2026, 8, 1)
VENTANA_FIN = date(2026, 9, 30)


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
# Texto
# ---------------------------------------------------------------------------
def sin_tildes(texto: str) -> str:
    """Quita tildes y diéresis conservando la ñ como n (suficiente para comparar)."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def clave_texto(texto: str | float | None) -> str | None:
    """Minúsculas, sin tildes y sin espacios sobrantes. None si el valor es nulo o vacío."""
    if texto is None or (isinstance(texto, float) and math.isnan(texto)):
        return None
    limpio = " ".join(sin_tildes(str(texto)).lower().split())
    return limpio or None


# ---------------------------------------------------------------------------
# Teléfono (TRD 6)
# ---------------------------------------------------------------------------
def normalizar_telefono(texto: str | float | None) -> str | None:
    """Deja solo dígitos, quita el prefijo 57 y valida 10 dígitos que empiezan por 3."""
    if texto is None or (isinstance(texto, float) and math.isnan(texto)):
        return None
    digitos = re.sub(r"\D", "", str(texto))
    if len(digitos) == 12 and digitos.startswith("57"):
        digitos = digitos[2:]
    if len(digitos) == 10 and digitos.startswith("3"):
        return digitos
    return None


def forma_telefono(texto: str) -> str:
    """Patrón de escritura del teléfono (dígitos -> 9) para contar formatos distintos."""
    return re.sub(r"\d", "9", str(texto))


# ---------------------------------------------------------------------------
# Fechas (TRD 6.1)
# ---------------------------------------------------------------------------
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$")
_DIA = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
_BARRAS = re.compile(r"^(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2})$")


def _crear(anio: int, mes: int, dia: int, hora: int = 0, minuto: int = 0) -> datetime | None:
    try:
        return datetime(anio, mes, dia, hora, minuto)
    except ValueError:
        return None


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


def lecturas_fecha(texto: str | float | None) -> tuple[list[tuple[datetime, str]], str]:
    """Devuelve las lecturas válidas posibles [(fecha, orden)] y la precisión ('minuto' o 'dia').

    Para el formato con barras, orden es 'ddmm' o 'mmdd'. Para los demás formatos, 'unica'.
    Una lista vacía significa fecha vacía o imposible.
    """
    formato = formato_fecha(texto)
    t = str(texto).strip() if formato != "vacio" else ""
    if formato in ("iso_espacio", "iso_t"):
        a, m, d, h, mi, _ = map(int, _ISO.match(t).groups())
        f = _crear(a, m, d, h, mi)
        return ([(f, "unica")] if f else []), "minuto"
    if formato == "dd-mm-yyyy":
        d, m, a = map(int, _DIA.match(t).groups())
        f = _crear(a, m, d)
        return ([(f, "unica")] if f else []), "dia"
    if formato == "barras":
        x, y, a, h, mi = map(int, _BARRAS.match(t).groups())
        opciones = []
        ddmm = _crear(a, y, x, h, mi)
        mmdd = _crear(a, x, y, h, mi)
        if ddmm:
            opciones.append((ddmm, "ddmm"))
        if mmdd and mmdd != ddmm:
            opciones.append((mmdd, "mmdd"))
        return opciones, "minuto"
    return [], "minuto"


def clase_barras(texto: str) -> str:
    """Para fechas con barras: 'ddmm' o 'mmdd' si un componente > 12, 'igual' si x = y, si no 'ambigua'."""
    x, y = (int(p) for p in str(texto).strip()[:5].split("/"))
    if x > 12:
        return "ddmm"
    if y > 12:
        return "mmdd"
    return "igual" if x == y else "ambigua"


def _en_ventana(f: datetime) -> bool:
    return VENTANA_INICIO <= f.date() <= VENTANA_FIN


def _comparables(a: datetime, b: datetime, por_dia: bool) -> tuple:
    return (a.date(), b.date()) if por_dia else (a, b)


def resolver_fecha(
    texto: str | float | None, otra: str | float | None, es_registro: bool
) -> tuple[datetime | None, str]:
    """Aplica la regla 6.1 del TRD a una fecha, usando la otra fecha del lead para la coherencia.

    Devuelve (fecha, motivo). Motivos: vacia, invalida, unica, componente_mayor_12, ventana,
    coherencia, por_defecto.
    """
    if formato_fecha(texto) == "vacio":
        return None, "vacia"
    opciones, precision = lecturas_fecha(texto)
    if not opciones:
        return None, "invalida"
    if len(opciones) == 1:
        orden = opciones[0][1]
        return opciones[0][0], ("unica" if orden == "unica" else "componente_mayor_12")

    # Paso 2: descartar lecturas fuera de la ventana de datos.
    en_ventana = [o for o in opciones if _en_ventana(o[0])]
    if len(en_ventana) == 1:
        return en_ventana[0][0], "ventana"
    candidatas = en_ventana or opciones

    # Paso 3: coherencia con la otra fecha (registro <= contacto).
    otras, precision_otra = lecturas_fecha(otra)
    otras = [o for o in otras if _en_ventana(o[0])] or otras
    if otras:
        por_dia = precision == "dia" or precision_otra == "dia"
        coherentes = []
        for fecha, orden in candidatas:
            for fecha_otra, _ in otras:
                a, b = _comparables(fecha, fecha_otra, por_dia)
                if (a <= b) if es_registro else (a >= b):
                    coherentes.append((fecha, orden))
                    break
        if len(coherentes) == 1:
            return coherentes[0][0], "coherencia"

    # Paso 4: empate -> dd/mm (convención colombiana).
    ddmm = next(f for f, orden in candidatas if orden == "ddmm")
    return ddmm, "por_defecto"


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
