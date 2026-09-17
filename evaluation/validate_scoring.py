"""Valida el puntaje v1 contra el histórico de cierres (RF-07, TRD 9.3).

Aplica el **componente A** del puntaje —el único con respaldo histórico— sobre los leads que sí
fueron gestionados, y comprueba que la temperatura separe los cierres. Los componentes B y C no se
validan aquí: el histórico no tiene señales de conversación ni permite reconstruir la espera.

Dos límites que se declaran siempre con las cifras:

1. **La validación temporal es parcial.** Los pesos se eligieron mirando las tasas de **todo** el
   histórico (docs/EDA.md, sección 4), ventana de prueba incluida, así que esa ventana no es una
   muestra que el puntaje no haya visto. Recalcularlos solo con el entrenamiento no mejora la
   prueba: la regresión sobre el entrenamiento ordena peor en la ventana de prueba.
2. **La muestra es pequeña.** En la ventana de prueba hay decenas de cierres por temperatura, así
   que cada tasa va con su intervalo de Wilson y la razón Caliente/Frío con uno por bootstrap. Si
   ese intervalo incluye el criterio, la razón es un indicio de separación, no un criterio cumplido.

Uso: `uv run python -m pipeline validate-scoring`
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from eda.comun import wilson  # noqa: E402
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
# Semilla fija: el informe tiene que dar lo mismo en cada corrida.
REMUESTREOS = 5000
SEMILLA = 2026


def preparar(historico: pd.DataFrame) -> pd.DataFrame:
    """Aplica el componente A sobre el histórico gestionado y marca la ventana de prueba."""
    df = historico[historico["desenlace"] != SIN_GESTION].copy()
    df["cerrado"] = (df["desenlace"] == "Cerrado").astype(int)
    presentes = senales(df)  # mismas claves que PESOS_CALIDAD
    df["puntos"] = sum(peso * presentes[clave] for clave, peso in PESOS_CALIDAD.items())
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


def intervalo(df: pd.DataFrame) -> str:
    """Intervalo de Wilson al 95 % de la tasa de cierre del grupo."""
    if df.empty:
        return "—"
    _, bajo, alto = wilson(int(df["cerrado"].sum()), len(df))
    return f"{coma(bajo * 100, 1)} – {coma(alto * 100, 1)} %"


def tabla_temperatura(df: pd.DataFrame) -> str:
    """Tasa de cierre por temperatura, en todo el histórico y en la ventana de prueba."""
    lineas = [
        "| Temperatura | Tasa (histórico con gestión) | n | Tasa (ventana de prueba) | IC 95 % | "
        "Cierres / n |",
        "|---|---|---|---|---|---|",
    ]
    for etiqueta in TEMPERATURAS:
        grupo = df[df["temperatura"] == etiqueta]
        prueba = grupo[grupo["prueba"]]
        n_todo, tasa_todo = tasa(grupo)
        n_prueba, tasa_prueba = tasa(prueba)
        lineas.append(
            f"| {etiqueta} | {coma(tasa_todo * 100, 1)} % | {n_todo} "
            f"| {coma(tasa_prueba * 100, 1)} % | {intervalo(prueba)} "
            f"| {int(prueba['cerrado'].sum())} / {n_prueba} |"
        )
    return "\n".join(lineas)


def razon_caliente_frio(df: pd.DataFrame) -> float:
    """Cuántas veces cierra más un Caliente que un Frío. Es el criterio de aceptación."""
    _, caliente = tasa(df[df["temperatura"] == "Caliente"])
    _, frio = tasa(df[df["temperatura"] == "Frío"])
    return caliente / frio if frio else float("nan")


def intervalo_razon(
    df: pd.DataFrame, remuestreos: int = REMUESTREOS, semilla: int = SEMILLA
) -> tuple[float, float]:
    """Intervalo al 95 % de la razón Caliente/Frío, por bootstrap de percentiles.

    Remuestrea cada grupo por separado, con reemplazo y su mismo tamaño. Los remuestreos sin
    cierres en Frío se descartan, porque la razón no está definida.
    """
    rng = np.random.default_rng(semilla)
    caliente = df.loc[df["temperatura"] == "Caliente", "cerrado"].to_numpy()
    frio = df.loc[df["temperatura"] == "Frío", "cerrado"].to_numpy()
    if not len(caliente) or not len(frio):
        return float("nan"), float("nan")
    tasas_c = rng.choice(caliente, (remuestreos, len(caliente))).mean(axis=1)
    tasas_f = rng.choice(frio, (remuestreos, len(frio))).mean(axis=1)
    razones = tasas_c[tasas_f > 0] / tasas_f[tasas_f > 0]
    bajo, alto = np.percentile(razones, [2.5, 97.5])
    return float(bajo), float(alto)


def auc_pesos_de_entrenamiento(entrenamiento: pd.DataFrame, prueba: pd.DataFrame) -> float:
    """AUC en prueba de unos pesos que no vieron la prueba: la alternativa a los pesos v1.

    Una regresión logística sobre las mismas cuatro señales del componente A, ajustada solo con el
    entrenamiento. Si ordena peor que v1 en la prueba, recalcular los pesos no aporta.
    """
    columnas = list(PESOS_CALIDAD)
    modelo = LogisticRegression().fit(senales(entrenamiento)[columnas], entrenamiento["cerrado"])
    return roc_auc_score(prueba["cerrado"], modelo.predict_proba(senales(prueba)[columnas])[:, 1])


def senales(df: pd.DataFrame) -> pd.DataFrame:
    """Las cuatro señales del componente A como columnas 0/1."""
    return pd.DataFrame({
        "cita": df["pidio_cita"].astype(int),
        "cuota": df["manifesto_cuota_inicial"].eq("SI").astype(int),
        "precio_alto": df["precio_lista"].ge(PRECIO_ALTO).astype(int),
        "contado": df["forma_pago_declarada"].eq("contado").astype(int),
    })  # fmt: skip


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
    print(
        f"Pesos derivados solo del entrenamiento (regresión logística con las mismas cuatro "
        f"señales): AUC {coma(auc_pesos_de_entrenamiento(entrenamiento, prueba), 3)} en prueba."
    )

    razon = razon_caliente_frio(prueba)
    bajo, alto = intervalo_razon(prueba)
    cumple = razon >= RAZON_MINIMA_CALIENTE_FRIO
    print(
        f"\nCriterio de aceptación: Caliente/Frío ≥ {coma(RAZON_MINIMA_CALIENTE_FRIO, 1)} "
        "en la ventana de prueba."
    )
    print(
        f"Resultado: {coma(razon)} veces (IC 95 % por bootstrap: {coma(bajo)} a {coma(alto)}) "
        f"→ {'CUMPLE' if cumple else 'NO CUMPLE'} en el valor puntual."
    )
    if bajo <= RAZON_MINIMA_CALIENTE_FRIO:
        print(
            "El intervalo incluye el criterio, así que es un **indicio de separación**, no un "
            "criterio demostrado."
        )
    print(
        "\nLimitación: los pesos se eligieron con todo el histórico, ventana de prueba incluida; "
        "la validación temporal es parcial."
    )
    return 0 if cumple else 1


if __name__ == "__main__":
    sys.exit(main())
