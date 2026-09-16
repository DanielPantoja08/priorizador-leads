"""Análisis del histórico de cierres: tasas con intervalos, AUC y validación temporal (TRD 17, punto 4)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from eda.comun import (
    cargar_csv,
    guardar_figura,
    miles,
    num,
    pct,
    tabla_md,
    wilson,
    z_dos_proporciones,
)
from pipeline.scoring import CORTE_TEMPORAL as _CORTE_TEMPORAL
from pipeline.scoring import PESOS_CALIDAD, PRECIO_ALTO, temperatura_de

# Entrenamiento antes de esta fecha, prueba desde ella (TRD 9.3). El histórico se lee como texto,
# así que se compara en formato ISO.
CORTE_TEMPORAL = _CORTE_TEMPORAL.isoformat()
TEMPERATURAS = ["Frío", "Tibio", "Caliente"]
SEMILLA = 0


def preparar(historico: pd.DataFrame, catalogo: pd.DataFrame) -> pd.DataFrame:
    """Convierte tipos y agrega las variables derivadas que usa el puntaje v1."""
    df = historico.copy()
    df["precio"] = df["precio_lista"].astype(int)
    df["horas"] = pd.to_numeric(df["horas_al_primer_contacto"])
    df["contactos"] = df["numero_contactos"].astype(int)
    df["cerrado"] = (df["desenlace"] == "Cerrado").astype(int)
    df["cita"] = (df["pidio_cita"] == "SI").astype(int)
    df["cuota"] = (df["manifesto_cuota_inicial"] == "SI").astype(int)
    df["precio_10m"] = (df["precio"] >= PRECIO_ALTO).astype(int)
    df["contado"] = (df["forma_pago_declarada"] == "contado").astype(int)
    segmentos = {f"{f.marca} {f.linea}": f.segmento for f in catalogo.itertuples()}
    df["segmento"] = df["modelo_cotizado"].map(segmentos)
    # Componente A del puntaje v1 (TRD 9.2). Los pesos y los cortes de temperatura salen de
    # `pipeline.scoring`: una sola fuente para el análisis, el pipeline y la validación.
    df["puntos_a"] = (
        PESOS_CALIDAD["cita"] * df["cita"]
        + PESOS_CALIDAD["cuota"] * df["cuota"]
        + PESOS_CALIDAD["precio_alto"] * df["precio_10m"]
        + PESOS_CALIDAD["contado"] * df["contado"]
    )
    df["temperatura"] = pd.Categorical(
        df["puntos_a"].map(temperatura_de), categories=TEMPERATURAS, ordered=True
    )
    df["prueba"] = df["fecha_registro"] >= CORTE_TEMPORAL
    return df


def tasa(df: pd.DataFrame) -> tuple[int, int, float]:
    """(cierres, n, tasa)."""
    n = len(df)
    cierres = int(df["cerrado"].sum())
    return cierres, n, (cierres / n if n else float("nan"))


def tasas_por_variable(g: pd.DataFrame, variable: str, etiqueta: str) -> tuple[list[list], int]:
    """Filas con n, cierres, tasa, IC 95 % y valor p de cada nivel frente al resto."""
    filas, no_significativas = [], 0
    for nivel, grupo in g.groupby(variable, observed=True):
        cierres, n, _ = tasa(grupo)
        resto = g[g[variable] != nivel]
        p_valor = z_dos_proporciones(cierres, n, int(resto["cerrado"].sum()), len(resto))
        _, bajo, alto = wilson(cierres, n)
        significativa = p_valor < 0.05
        no_significativas += not significativa
        filas.append([
            etiqueta, f"`{nivel}`", miles(n), cierres, pct(cierres / n),
            f"{pct(bajo)} – {pct(alto)}", num(p_valor, 3), "sí" if significativa else "**no**",
        ])  # fmt: skip
    return filas, no_significativas


def comparar(g: pd.DataFrame, condicion: pd.Series, otra: pd.Series | None = None) -> tuple:
    """Tasa donde se cumple la condición y donde no (o donde se cumple `otra`)."""
    si = g[condicion]
    no = g[otra] if otra is not None else g[~condicion]
    return tasa(si), tasa(no)


def regresion_logistica(g: pd.DataFrame) -> dict:
    """AUC de una regresión logística con los atributos disponibles al registrar el lead.

    Variables: canal, manifestó cuota (3 niveles), forma de pago (3 niveles), pidió cita y precio en millones.
    Se excluyen `numero_contactos` (fuga) y `horas_al_primer_contacto` (depende de la gestión, no del lead).
    """
    x = pd.get_dummies(
        g[["canal", "manifesto_cuota_inicial", "forma_pago_declarada"]],
        drop_first=True,
        dtype=float,
    )
    x["cita"] = g["cita"].astype(float)
    x["precio_millones"] = g["precio"] / 1_000_000
    y = g["cerrado"].to_numpy()
    modelo = LogisticRegression(max_iter=1000)

    validacion = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEMILLA)
    probas_cv = cross_val_predict(modelo, x, y, cv=validacion, method="predict_proba")[:, 1]

    entrenamiento = ~g["prueba"].to_numpy()
    modelo.fit(x[entrenamiento], y[entrenamiento])
    auc_prueba = roc_auc_score(y[~entrenamiento], modelo.predict_proba(x[~entrenamiento])[:, 1])
    modelo.fit(x, y)
    auc_muestra = roc_auc_score(y, modelo.predict_proba(x)[:, 1])
    return {
        "auc_cv": roc_auc_score(y, probas_cv),
        "auc_prueba": auc_prueba,
        "auc_muestra": auc_muestra,
        "variables": list(x.columns),
    }


def figura_horas(g: pd.DataFrame) -> str:
    """Tasa de cierre por horas al primer contacto, con IC 95 %."""
    niveles = sorted(g["horas"].unique())
    tasas, errores_bajo, errores_alto = [], [], []
    for h in niveles:
        grupo = g[g["horas"] == h]
        p, bajo, alto = wilson(int(grupo["cerrado"].sum()), len(grupo))
        tasas.append(p * 100)
        errores_bajo.append((p - bajo) * 100)
        errores_alto.append((alto - p) * 100)
    fig, eje = plt.subplots(figsize=(8, 3.5))
    posiciones = np.arange(len(niveles))
    eje.errorbar(posiciones, tasas, yerr=[errores_bajo, errores_alto], fmt="o-", capsize=4)
    eje.set_xticks(posiciones, [f"{h:g}" for h in niveles])
    eje.set_xlabel("Horas al primer contacto")
    eje.set_ylabel("% de cierre")
    eje.set_title("Cierre por velocidad de contacto (histórico con gestión, IC 95 %)")
    eje.grid(alpha=0.3)
    return guardar_figura(fig, "cierre_por_horas.png")


def figura_temperatura(g: pd.DataFrame) -> str:
    """Tasa de cierre por temperatura, histórico completo frente a ventana de prueba."""
    etiquetas = ["Frío", "Tibio", "Caliente"]
    completo = [tasa(g[g["temperatura"] == t])[2] * 100 for t in etiquetas]
    prueba = [tasa(g[(g["temperatura"] == t) & g["prueba"]])[2] * 100 for t in etiquetas]
    fig, eje = plt.subplots(figsize=(6, 3.5))
    posiciones = np.arange(len(etiquetas))
    eje.bar(posiciones - 0.2, completo, 0.4, label="Todo el histórico")
    eje.bar(posiciones + 0.2, prueba, 0.4, label=f"Prueba (≥ {CORTE_TEMPORAL})")
    eje.set_xticks(posiciones, etiquetas)
    eje.set_ylabel("% de cierre")
    eje.set_title("Cierre por temperatura (componente A del puntaje v1)")
    eje.legend()
    return guardar_figura(fig, "cierre_por_temperatura.png")


def analizar(catalogo: pd.DataFrame | None = None) -> dict:
    """Ejecuta el análisis del histórico y devuelve secciones Markdown y cifras."""
    catalogo = catalogo if catalogo is not None else cargar_csv("catalogo_motos.csv")
    df = preparar(cargar_csv("historico_cierres.csv"), catalogo)
    g = df[df["desenlace"] != "Sin gestión"].copy()  # histórico con gestión
    sin_gestion = df[df["desenlace"] == "Sin gestión"]
    cifras: dict = {}

    # Tasas base
    cierres, n, base = tasa(df)
    cierres_g, n_g, base_g = tasa(g)
    cifras.update(
        tasa_base=base, cierres=cierres, n_historico=n, tasa_gestion=base_g, n_gestion=n_g,
        n_sin_gestion=len(sin_gestion), rango=(df["fecha_registro"].min(), df["fecha_registro"].max()),
    )  # fmt: skip

    # Exclusión de "Sin gestión" y fuga de numero_contactos
    exclusion = tabla_md(
        ["Desenlace", "n", "Horas al primer contacto nulas", "numero_contactos = 0", "Cierres"],
        [
            [
                d,
                miles(len(grupo)),
                int(grupo["horas"].isna().sum()),
                int((grupo["contactos"] == 0).sum()),
                int(grupo["cerrado"].sum()),
            ]
            for d, grupo in df.groupby("desenlace")
        ],
    )
    filas_contactos, _ = tasas_por_variable(g, "contactos", "numero_contactos")

    # Tasas por variable con IC y significancia
    filas, no_sig = [], 0
    for variable, etiqueta in [
        ("canal", "Canal"),
        ("empresa_id", "Empresa"),
        ("segmento", "Segmento"),
        ("manifesto_cuota_inicial", "Manifestó cuota"),
        ("forma_pago_declarada", "Forma de pago"),
        ("pidio_cita", "Pidió cita"),
        ("precio_10m", "Precio ≥ $10 M"),
        ("horas", "Horas al primer contacto"),
    ]:
        nuevas, ns = tasas_por_variable(g, variable, etiqueta)
        filas += nuevas
        no_sig += ns
    tabla_variables = tabla_md(
        [
            "Variable",
            "Nivel",
            "n",
            "Cierres",
            "Tasa",
            "IC 95 %",
            "p frente al resto",
            "¿Significativa?",
        ],
        filas,
    )

    # Tabla 9.2
    (c_si, c_no) = comparar(g, g["cita"] == 1)
    (q_si, q_no) = comparar(g, g["cuota"] == 1)
    (q_si2, q_no_solo) = comparar(g, g["cuota"] == 1, g["manifesto_cuota_inicial"] == "NO")
    (p_si, p_no) = comparar(g, g["precio_10m"] == 1)
    (f_contado, f_credito) = comparar(
        g, g["forma_pago_declarada"] == "contado", g["forma_pago_declarada"] == "credito"
    )
    f_no_informa = tasa(g[g["forma_pago_declarada"] == "no_informa"])
    cifras.update(
        cita_si=c_si[2], cita_no=c_no[2], cuota_si=q_si[2], cuota_no=q_no[2], cuota_no_solo=q_no_solo[2],
        precio_si=p_si[2], precio_no=p_no[2], contado=f_contado[2], credito=f_credito[2], pago_no_informa=f_no_informa[2],
    )  # fmt: skip

    def fila_92(factor, si, no, detalle_no):
        p_valor = z_dos_proporciones(si[0], si[1], no[0], no[1])
        return [
            factor,
            f"{pct(si[2])} (n={miles(si[1])})",
            f"{pct(no[2])} (n={miles(no[1])}, {detalle_no})",
            num(p_valor, 3),
        ]

    tabla_92 = tabla_md(
        ["Factor", "Tasa si se cumple", "Tasa si no", "p"],
        [
            fila_92("Pidió cita", c_si, c_no, "NO"),
            fila_92("Manifestó cuota inicial", q_si, q_no, "NO + NO_INFORMA"),
            fila_92("Manifestó cuota inicial (solo contra NO)", q_si2, q_no_solo, "solo NO"),
            fila_92("Precio del modelo ≥ $10 M", p_si, p_no, "< $10 M"),
            fila_92("Pago de contado", f_contado, f_credito, "crédito"),
            fila_92("Forma de pago no informa", f_no_informa, f_credito, "crédito"),
        ],
    )

    # Horas al primer contacto
    horas = {h: tasa(g[g["horas"] == h]) for h in sorted(g["horas"].unique())}
    cifras.update(horas_1=horas[1.0][2], horas_24=horas[24.0][2], horas_120=horas[120.0][2])

    # AUC
    rl = regresion_logistica(g)
    auc_v1 = roc_auc_score(g["cerrado"], g["puntos_a"])
    auc_v1_train = roc_auc_score(g.loc[~g["prueba"], "cerrado"], g.loc[~g["prueba"], "puntos_a"])
    auc_v1_test = roc_auc_score(g.loc[g["prueba"], "cerrado"], g.loc[g["prueba"], "puntos_a"])
    cifras.update(
        auc_rl_cv=rl["auc_cv"], auc_rl_prueba=rl["auc_prueba"], auc_rl_muestra=rl["auc_muestra"],
        auc_v1=auc_v1, auc_v1_train=auc_v1_train, auc_v1_test=auc_v1_test,
        n_train=int((~g["prueba"]).sum()), n_test=int(g["prueba"].sum()),
    )  # fmt: skip
    tabla_auc = tabla_md(
        ["Modelo", "Evaluación", "AUC"],
        [
            [
                "Regresión logística",
                "Validación cruzada estratificada de 5 pliegues (semilla 0), todo el histórico con gestión",
                num(rl["auc_cv"]),
            ],
            [
                "Regresión logística",
                f"Entrenada antes del {CORTE_TEMPORAL}, evaluada desde esa fecha",
                num(rl["auc_prueba"]),
            ],
            ["Regresión logística", "Dentro de muestra (optimista)", num(rl["auc_muestra"])],
            [
                "Puntaje v1 (componente A)",
                "Todo el histórico con gestión (sin ajuste)",
                num(auc_v1),
            ],
            [
                "Puntaje v1 (componente A)",
                f"Antes del {CORTE_TEMPORAL} (n={miles(cifras['n_train'])})",
                num(auc_v1_train),
            ],
            [
                "Puntaje v1 (componente A)",
                f"Desde el {CORTE_TEMPORAL} (n={miles(cifras['n_test'])})",
                num(auc_v1_test),
            ],
        ],
    )

    # Tabla 9.3
    filas_93 = []
    for t in ["Frío", "Tibio", "Caliente"]:
        todo = tasa(g[g["temperatura"] == t])
        prueba = tasa(g[(g["temperatura"] == t) & g["prueba"]])
        cifras[f"t93_{t}"] = todo
        cifras[f"t93_{t}_prueba"] = prueba
        filas_93.append([t, pct(todo[2]), miles(todo[1]), pct(prueba[2]), miles(prueba[1])])
    razon = cifras["t93_Caliente_prueba"][2] / cifras["t93_Frío_prueba"][2]
    razon_todo = cifras["t93_Caliente"][2] / cifras["t93_Frío"][2]
    cifras.update(razon_prueba=razon, razon_todo=razon_todo)
    _, bajo_c, alto_c = wilson(*cifras["t93_Caliente_prueba"][:2])
    _, bajo_f, alto_f = wilson(*cifras["t93_Frío_prueba"][:2])
    tabla_93 = tabla_md(
        [
            "Temperatura",
            "Tasa (todo el histórico)",
            "n",
            f"Tasa en prueba (≥ {CORTE_TEMPORAL})",
            "n",
        ],
        filas_93,
    )

    return {
        "exclusion": exclusion,
        "contactos": tabla_md(
            [
                "Variable",
                "Nivel",
                "n",
                "Cierres",
                "Tasa",
                "IC 95 %",
                "p frente al resto",
                "¿Significativa?",
            ],
            filas_contactos,
        ),
        "variables": tabla_variables,
        "no_significativas": no_sig,
        "tabla_92": tabla_92,
        "tabla_auc": tabla_auc,
        "variables_rl": rl["variables"],
        "tabla_93": tabla_93,
        "ic_prueba": (bajo_c, alto_c, bajo_f, alto_f),
        "figura_horas": figura_horas(g),
        "figura_temperatura": figura_temperatura(g),
        "cifras": cifras,
    }


if __name__ == "__main__":  # diagnóstico rápido: uv run python -m eda.historico
    for clave, valor in analizar()["cifras"].items():
        print(f"{clave}: {valor}")
