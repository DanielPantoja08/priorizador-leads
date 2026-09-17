"""Simula qué habría pasado con el histórico si se hubiera priorizado (RF-07, TRD 9.3).

`validate_scoring` responde si el puntaje **ordena**; esto responde la pregunta del gerente:
**cuántos cierres más entran con la misma gente y las mismas horas.**

El ejercicio es contrafactual y se corre en dos escenarios, porque el supuesto pesa más que la
política:

1. **Sin decaimiento.** El desenlace es propiedad del lead, no del momento en que se atendió: si
   entra en el cupo del día, cierra como cerró; si queda fuera, se pierde.
2. **Con espera.** Un lead que queda fuera del cupo **no se pierde**: pasa al día siguiente, y
   después de `DIAS_MAXIMOS_DE_ESPERA` (lo máximo que el histórico observa) se da por perdido.
   Este escenario es **simétrico**: no usa el desenlace de cada lead, que ya trae incorporada la
   espera que tuvo. Cada lead tiene una probabilidad base —la tasa de cierre de su temperatura
   entre los leads contactados en menos de 24 h— que la espera reduce. Atender rápido a un lead
   que en la realidad no cerró también suma.

   **El efecto de la espera es observacional, no causal.** Quien recibe respuesta en menos de 24 h
   cierra más, pero quizá porque se contesta antes a los mejores leads. Por eso se reporta con tres
   supuestos: que nada de esa diferencia es causa de la espera (0 %), que lo es la mitad (50 %) o
   toda (100 %). La cifra real está en ese rango, no en uno de sus extremos.

Aclaraciones:

1. El histórico trae la fecha sin hora, así que **el orden de llegada dentro del día se aproxima
   con el `lead_id`**, que es correlativo y no tiene relación con el puntaje. No es el orden real,
   pero es un orden independiente de lo que se quiere medir.
2. Se incluye una política **al azar** como control: si la ganancia del puntaje fuera ruido del
   tamaño de la muestra, el azar daría algo parecido.
3. Con decaimiento, «más reciente primero» es el control justo: separa lo que se gana por
   atender fresco de lo que se gana por ordenar según el puntaje. Frente al orden de llegada con
   pendientes cualquier política fresca gana mucho, porque ese orden atiende siempre lo más viejo.
4. La política completa suma la urgencia del componente C calculada con `pipeline/scoring.py`.
   El componente B no entra: el histórico no tiene conversaciones.
5. La probabilidad base es por temperatura y no por puntaje exacto: los grupos de 7 a 9 puntos
   tienen pocas decenas de leads y sus tasas no son monótonas. Eso subestima lo que aporta ordenar
   dentro de una misma temperatura, y sale del mismo histórico que definió el puntaje.

Uso: `uv run python -m pipeline simulate-policy`
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from evaluation.validate_scoring import coma, preparar  # noqa: E402
from pipeline.ingest import leer_csv  # noqa: E402
from pipeline.normalize import normalizar_historico  # noqa: E402
from pipeline.scoring import ESTADO_SIN_GESTION, _urgencia  # noqa: E402

# Fracción de la demanda diaria que el equipo alcanza a gestionar. En los datos actuales hay 981
# leads elegibles para 694 de capacidad (71 %), así que 0,7 es el escenario que refleja la realidad.
CAPACIDADES = (0.5, 0.7, 0.9, 1.0)
CAPACIDAD_REAL = 0.7
REPETICIONES_AZAR = 200
SEMILLA = 20260916
DIAS_DEL_MES = 30
# El histórico no tiene primeros contactos después de 120 h: más allá no hay tasa que usar.
DIAS_MAXIMOS_DE_ESPERA = 5
# Sin hora en el histórico, un lead del día se toma a mitad de jornada.
HORAS_DEL_DIA_DE_LLEGADA = 12
# Qué parte de la diferencia de cierre por espera se supone causada por la espera.
EFECTOS_CAUSALES = (0.0, 0.5, 1.0)


def dias_de(df: pd.DataFrame) -> list[pd.DataFrame]:
    """Parte el histórico en jornadas: la capacidad se agota y se renueva cada día."""
    return [grupo for _, grupo in df.groupby("fecha_registro", sort=True)]


def cupo(leads_del_dia: int, fraccion: float) -> int:
    """Cuántos leads alcanza a gestionar el equipo ese día. Siempre atiende al menos uno."""
    return max(1, math.ceil(leads_del_dia * fraccion))


def por_llegada(dia: pd.DataFrame) -> pd.DataFrame:
    """Lo que se hace hoy: el que llegó primero se atiende primero."""
    return dia.sort_values("lead_id")


def por_puntaje(dia: pd.DataFrame) -> pd.DataFrame:
    """Lo que propone el priorizador. A igualdad de puntos manda la llegada."""
    return dia.sort_values(["puntos", "lead_id"], ascending=[False, True])


def cierres_capturados(
    dias: list[pd.DataFrame], ordenar: Callable[[pd.DataFrame], pd.DataFrame], fraccion: float
) -> int:
    """Cierres que quedan dentro del cupo diario al aplicar esa política."""
    return sum(int(ordenar(dia).head(cupo(len(dia), fraccion))["cerrado"].sum()) for dia in dias)


def cierres_al_azar(
    dias: list[pd.DataFrame],
    fraccion: float,
    repeticiones: int = REPETICIONES_AZAR,
    semilla: int = SEMILLA,
) -> float:
    """Control: cierres promedio si se atendiera en orden arbitrario. Determinista por la semilla."""
    generador = np.random.default_rng(semilla)
    corridas = [
        cierres_capturados(dias, lambda dia: dia.sample(frac=1, random_state=generador), fraccion)
        for _ in range(repeticiones)
    ]
    return sum(corridas) / repeticiones


def comparar(dias: list[pd.DataFrame], fraccion: float) -> dict[str, float]:
    """Las tres políticas sobre la misma capacidad."""
    llegada = cierres_capturados(dias, por_llegada, fraccion)
    puntaje = cierres_capturados(dias, por_puntaje, fraccion)
    return {
        "capacidad": fraccion,
        "llegada": llegada,
        "azar": cierres_al_azar(dias, fraccion),
        "puntaje": puntaje,
        "ganancia": puntaje - llegada,
        "ganancia_pct": (puntaje - llegada) / llegada * 100 if llegada else float("nan"),
    }


def factores_de_espera(df: pd.DataFrame) -> dict[int, float]:
    """Cuánto conserva un lead de su probabilidad de cierre según los días que esperó.

    Es la tasa de cierre con esa espera (días completos hasta el primer contacto) sobre la tasa con
    menos de 24 h. Se fuerza a no crecer con la espera: un repunte entre días vecinos es ruido de
    muestra, no una razón para demorar a nadie.
    """
    dias = (df["horas_al_primer_contacto"] // 24).astype(int)
    tasas = df.groupby(dias)["cerrado"].mean()
    factores, actual = {}, 1.0
    for dia in range(DIAS_MAXIMOS_DE_ESPERA + 1):
        if dia in tasas.index:
            actual = min(actual, tasas.loc[dia] / tasas.loc[0])
        factores[dia] = actual
    return factores


def probabilidad_base(df: pd.DataFrame, factores: dict[int, float], efecto: float) -> pd.Series:
    """Probabilidad de cierre de cada lead si se atiende el mismo día, según su temperatura.

    No usa el desenlace del propio lead, así que atenderlo antes puede sumar aunque en la realidad
    no cerró. Se calibra con el supuesto causal: es la que, con las esperas que de verdad tuvo cada
    lead, reproduce los cierres observados de su temperatura. Con efecto 0 es la tasa promedio; con
    efecto 1 se le devuelve lo que la espera observada le habría quitado.
    """
    dias_reales = (df["horas_al_primer_contacto"] // 24).astype(int).clip(0, DIAS_MAXIMOS_DE_ESPERA)
    df = df.assign(_conserva=conserva(dias_reales, factores, efecto))
    grupos = df.groupby("temperatura")
    return df["temperatura"].map(grupos["cerrado"].sum() / grupos["_conserva"].sum())


def conserva(dias: pd.Series, factores: dict[int, float], efecto: float) -> pd.Series:
    """Qué parte de su probabilidad conserva cada lead tras esperar, con `efecto` causal (0 a 1)."""
    return dias.map(lambda d: 1 - efecto * (1 - factores[d]))


def atendidos_con_espera(
    df: pd.DataFrame, ordenar: Callable[[pd.DataFrame], pd.DataFrame], fraccion: float
) -> pd.Series:
    """Días que esperó cada lead atendido, si lo que no cabe hoy pasa a mañana.

    El cupo de cada día es el mismo del escenario sin espera (una fracción de lo que llegó ese
    día), pero se reparte entre lo nuevo y lo pendiente según la política. Qué se atiende no
    depende del supuesto causal, así que se calcula una sola vez por política y capacidad.
    """
    fechas = pd.to_datetime(df["fecha_registro"])
    pendientes = df.iloc[0:0]
    esperas = []
    for dia in sorted(fechas.unique()):
        cola = pd.concat([pendientes, df[fechas == dia]])
        espera = (dia - pd.to_datetime(cola["fecha_registro"])).dt.days
        cola = cola[espera <= DIAS_MAXIMOS_DE_ESPERA]  # los demás ya se perdieron
        atendidos = ordenar(cola).head(cupo(int((fechas == dia).sum()), fraccion))
        esperas.append((dia - pd.to_datetime(atendidos["fecha_registro"])).dt.days)
        pendientes = cola.drop(atendidos.index)
    return pd.concat(esperas) if esperas else pd.Series(dtype=int)


def cierres_esperados(
    esperas: pd.Series, base: pd.Series, factores: dict[int, float], efecto: float
) -> float:
    """Suma de probabilidades de los atendidos, con `efecto` de la caída por espera como causal."""
    return float((base.loc[esperas.index] * conserva(esperas, factores, efecto)).sum())


def por_llegada_con_pendientes(cola: pd.DataFrame) -> pd.DataFrame:
    """Orden de llegada con pendientes: primero lo más antiguo."""
    return cola.sort_values(["fecha_registro", "lead_id"])


def por_puntaje_con_pendientes(cola: pd.DataFrame) -> pd.DataFrame:
    """Por puntaje; a igualdad de puntos, lo más antiguo."""
    return cola.sort_values(["puntos", "fecha_registro", "lead_id"], ascending=[False, True, True])


def por_puntaje_con_urgencia(cola: pd.DataFrame) -> pd.DataFrame:
    """La política real: calidad más la urgencia del componente C, que baja con la espera.

    El histórico no trae hora, así que un lead del día se toma a mitad de jornada (12 h) y cada
    día de espera suma 24 h. A igualdad, lo más antiguo, como en `pipeline/scoring.py`.
    """
    dia = pd.to_datetime(cola["fecha_registro"]).max()
    horas = (dia - pd.to_datetime(cola["fecha_registro"])).dt.days * 24 + HORAS_DEL_DIA_DE_LLEGADA
    urgencia = horas.map(lambda h: _urgencia(ESTADO_SIN_GESTION, h)[0])
    return (
        cola.assign(_prioridad=cola["puntos"] + urgencia)
        .sort_values(["_prioridad", "fecha_registro", "lead_id"], ascending=[False, True, True])
        .drop(columns="_prioridad")
    )


def mas_reciente_primero(cola: pd.DataFrame) -> pd.DataFrame:
    """Control sin puntaje: primero lo que acaba de llegar, que es lo que todavía no se enfrió."""
    return cola.sort_values(["fecha_registro", "lead_id"], ascending=[False, True])


def tabla_con_espera(df: pd.DataFrame, factores: dict[int, float]) -> str:
    """Cierres esperados por supuesto causal, capacidad y política.

    «Más reciente primero» separa los dos efectos: lo que gana frente a la llegada es atender fresco;
    lo que el puntaje gana frente a ella es el orden por calidad.
    """
    politicas = {
        "llegada": por_llegada_con_pendientes,
        "reciente": mas_reciente_primero,
        "calidad": por_puntaje_con_pendientes,
        "completo": por_puntaje_con_urgencia,
    }
    esperas = {
        (nombre, fraccion): atendidos_con_espera(df, ordenar, fraccion)
        for nombre, ordenar in politicas.items()
        for fraccion in CAPACIDADES
    }
    lineas = [
        "| Efecto causal de la espera | Capacidad diaria | Orden de llegada | Más reciente primero "
        "| Solo calidad (A) | **Calidad + urgencia (A + C)** | Ganancia sobre el más reciente |",
        "|---|---|---|---|---|---|---|",
    ]
    for efecto in EFECTOS_CAUSALES:
        base = probabilidad_base(df, factores, efecto)
        for fraccion in CAPACIDADES:
            c = {
                nombre: cierres_esperados(esperas[(nombre, fraccion)], base, factores, efecto)
                for nombre in politicas
            }
            ganancia = c["completo"] - c["reciente"]
            lineas.append(
                f"| {efecto * 100:.0f} % | {fraccion * 100:.0f} % de la demanda "
                f"| {coma(c['llegada'], 1)} | {coma(c['reciente'], 1)} | {coma(c['calidad'], 1)} "
                f"| **{coma(c['completo'], 1)}** | {'+' if ganancia >= 0 else ''}{coma(ganancia, 1)} "
                f"({coma(ganancia / c['reciente'] * 100, 1)} %) |"
            )
    return "\n".join(lineas)


def tabla(resultados: list[dict]) -> str:
    """Tabla de cierres capturados por política y capacidad."""
    lineas = [
        "| Capacidad diaria | Orden de llegada | Al azar | **Priorizado** | Ganancia |",
        "|---|---|---|---|---|",
    ]
    for r in resultados:
        lineas.append(
            f"| {r['capacidad'] * 100:.0f} % de la demanda | {r['llegada']} | {coma(r['azar'], 1)} "
            f"| **{r['puntaje']}** | {r['ganancia']:+d} ({coma(r['ganancia_pct'], 1)} %) |"
        )
    return "\n".join(lineas)


def main() -> int:
    """Imprime la comparación. Devuelve 0 siempre: es una medición, no un criterio de aceptación."""
    historico = preparar(normalizar_historico(leer_csv("historico_cierres.csv")))
    dias = dias_de(historico)
    cierres = int(historico["cerrado"].sum())

    print("Simulación de política de atención · TRD 9.3\n")
    print(f"Histórico con gestión: {len(historico)} leads en {len(dias)} días · {cierres} cierres")
    print("Supuesto: un lead que queda fuera del cupo del día no se gestiona y no cierra.\n")

    resultados = [comparar(dias, fraccion) for fraccion in CAPACIDADES]
    print(tabla(resultados))

    real = next(r for r in resultados if r["capacidad"] == CAPACIDAD_REAL)
    por_mes = real["ganancia"] / len(dias) * DIAS_DEL_MES
    print(
        f"\nCon capacidad para el {CAPACIDAD_REAL * 100:.0f} % de la demanda —la proporción que se "
        f"observa hoy: 694 de cupo para 981 leads elegibles— atender por puntaje en vez de por "
        f"orden de llegada captura **{real['ganancia']} cierres más** sobre el mismo histórico "
        f"({coma(real['ganancia_pct'], 1)} % más), equivalente a {coma(por_mes, 1)} al mes."
    )
    print(
        "El azar sirve de control: si el puntaje no separara, su columna se parecería a la de la "
        "llegada. Con capacidad para todos, ninguna política gana: no sobra nadie por atender."
    )

    factores = factores_de_espera(historico)
    print("\n### Con espera: simétrico y con supuesto causal explícito\n")
    print(
        f"Lo que no cabe hoy pasa a mañana; después de {DIAS_MAXIMOS_DE_ESPERA} días se pierde. "
        "Caída observada según los días de espera: "
        + ", ".join(f"{dia} d → {coma(f * 100, 0)} %" for dia, f in factores.items())
        + ". Con efecto causal x, un lead conserva 1 − x · (1 − caída). La probabilidad base de "
        "cada temperatura se calibra para que, con las esperas reales, dé los cierres observados.\n"
    )
    print(tabla_con_espera(historico, factores))
    print(
        "\nEl efecto de la espera es observacional: la cifra defendible es el rango entre 0 % y "
        "100 %, no uno de sus extremos."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
