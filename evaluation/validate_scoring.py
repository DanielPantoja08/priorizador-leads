"""Valida el puntaje v1 contra el histórico de cierres (RF-07, TRD 9.3).

Aplica el **componente A** del puntaje —el único con respaldo histórico— sobre los leads que sí
fueron gestionados, y comprueba que la temperatura separe los cierres. Los componentes B y C no se
validan aquí: el histórico no tiene señales de conversación ni permite reconstruir la espera.

La prueba real es la **temporal**: los pesos se fijaron mirando todo el histórico, así que medirlos
otra vez sobre esos mismos datos sería optimista. Por eso el criterio de aceptación se exige sobre
la ventana posterior al corte, que no participó en la decisión de los pesos.

Uso: `uv run python -m pipeline validate-scoring`
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import roc_auc_score

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pipeline.ingest import leer_csv  # noqa: E402
from pipeline.normalize import normalizar_historico  # noqa: E402
from pipeline.scoring import (  # noqa: E402
    CORTE_TEMPORAL,
    PESOS_CALIDAD,
    PRECIO_ALTO,
    RAZON_MINIMA_CALIENTE_FRIO,
    VERSION_SCORE,
    temperatura_de,
)

TEMPERATURAS = ("Frío", "Tibio", "Caliente")
# Los leads que nunca se gestionaron no dicen nada de la calidad del lead: su desenlace refleja
# que nadie los llamó, no que fueran malos (TRD 9.1).
SIN_GESTION = "Sin gestión"


def preparar(historico: pd.DataFrame) -> pd.DataFrame:
    """Aplica el componente A sobre el histórico gestionado y marca la ventana de prueba."""
    df = historico[historico["desenlace"] != SIN_GESTION].copy()
    df["cerrado"] = (df["desenlace"] == "Cerrado").astype(int)
    df["puntos"] = (
        PESOS_CALIDAD["cita"] * df["pidio_cita"].astype(int)
        + PESOS_CALIDAD["cuota"] * df["manifesto_cuota_inicial"].eq("SI").astype(int)
        + PESOS_CALIDAD["precio_alto"] * df["precio_lista"].ge(PRECIO_ALTO).astype(int)
        + PESOS_CALIDAD["contado"] * df["forma_pago_declarada"].eq("contado").astype(int)
    )
    df["temperatura"] = df["puntos"].map(temperatura_de)
    df["prueba"] = df["fecha_registro"] >= CORTE_TEMPORAL
    return df


def coma(valor: float, decimales: int = 2) -> str:
    """Número con coma decimal, como se escribe en español. No toca el resto de la frase."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def tasa(df: pd.DataFrame) -> tuple[int, float]:
    """(n, tasa de cierre). La tasa es NaN si el grupo está vacío."""
    n = len(df)
    return n, (df["cerrado"].sum() / n if n else float("nan"))


def tabla_temperatura(df: pd.DataFrame) -> str:
    """Tasa de cierre por temperatura, en todo el histórico y en la ventana de prueba."""
    lineas = [
        "| Temperatura | Tasa (histórico con gestión) | n | Tasa (validación temporal) | n |",
        "|---|---|---|---|---|",
    ]
    for etiqueta in TEMPERATURAS:
        grupo = df[df["temperatura"] == etiqueta]
        n_todo, tasa_todo = tasa(grupo)
        n_prueba, tasa_prueba = tasa(grupo[grupo["prueba"]])
        lineas.append(
            f"| {etiqueta} | {coma(tasa_todo * 100, 1)} % | {n_todo} "
            f"| {coma(tasa_prueba * 100, 1)} % | {n_prueba} |"
        )
    return "\n".join(lineas)


def razon_caliente_frio(df: pd.DataFrame) -> float:
    """Cuántas veces cierra más un Caliente que un Frío. Es el criterio de aceptación."""
    _, caliente = tasa(df[df["temperatura"] == "Caliente"])
    _, frio = tasa(df[df["temperatura"] == "Frío"])
    return caliente / frio if frio else float("nan")


def main() -> int:
    """Imprime el informe y devuelve 0 si el puntaje cumple el criterio, o 1 si no lo cumple."""
    df = preparar(normalizar_historico(leer_csv("historico_cierres.csv")))
    entrenamiento, prueba = df[~df["prueba"]], df[df["prueba"]]

    print(f"Validación del puntaje {VERSION_SCORE} (componente A) · TRD 9.3\n")
    print(f"Histórico con gestión: {len(df)} leads · corte temporal {CORTE_TEMPORAL}")
    print(f"Entrenamiento: {len(entrenamiento)} · Prueba: {len(prueba)}\n")
    print(tabla_temperatura(df))

    auc_entrenamiento = roc_auc_score(entrenamiento["cerrado"], entrenamiento["puntos"])
    auc_prueba = roc_auc_score(prueba["cerrado"], prueba["puntos"])
    print(
        f"\nAUC: {coma(auc_entrenamiento, 3)} en entrenamiento y {coma(auc_prueba, 3)} en prueba."
    )
    print("El puntaje ordena, no predice con certeza: un AUC cercano a 0,6 es ordenamiento débil.")

    razon = razon_caliente_frio(prueba)
    cumple = razon >= RAZON_MINIMA_CALIENTE_FRIO
    veredicto = "CUMPLE" if cumple else "NO CUMPLE"
    print(
        f"\nCriterio de aceptación: Caliente/Frío ≥ {coma(RAZON_MINIMA_CALIENTE_FRIO, 1)} "
        "en la ventana de prueba."
    )
    print(f"Resultado: {coma(razon)} veces → {veredicto}")
    return 0 if cumple else 1


if __name__ == "__main__":
    sys.exit(main())
