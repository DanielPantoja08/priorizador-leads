"""Análisis de las conversaciones de WhatsApp (TRD 17, punto 5).

Las frecuencias de objeciones e intenciones se miden con palabras clave. Son una APROXIMACIÓN para dimensionar
el problema, no una etiqueta: la extracción real la hace el componente de IA (Fase C).
"""

from __future__ import annotations

import re
from collections import Counter
from statistics import mean, median

import matplotlib.pyplot as plt
import pandas as pd

from eda.comun import (
    cargar_conversaciones,
    cargar_csv,
    clave_texto,
    guardar_figura,
    miles,
    pct,
    tabla_md,
)

# Montos con unidades o jerga (TRD 8.2 y 8.3). Se buscan sobre el texto del cliente sin tildes.
PATRONES_MONTO = {
    "millones": r"\b\d+(?:[.,]\d+)?\s*millones\b",
    "palos": r"\b\d+(?:[.,]\d+)?\s*palos\b",
    "millonzitos": r"\b\d+(?:[.,]\d+)?\s*millonzitos\b",
    "Nmil (p. ej. 1500mil)": r"\b\d+\s*mil\b",
    "$ con puntos (p. ej. $2.000.000)": r"\$\s*\d{1,3}(?:\.\d{3})+",
}
CERO_MILLONES = r"\b0\s*(?:millones|palos|millonzitos)\b"

# Palabras clave por objeción (enumeración de TRD 8.1).
OBJECIONES = {
    "precio": [
        "muy cara",
        "costosa",
        "presupuesto",
        "por encima de lo que tengo",
        "algo mas economico",
    ],
    # "interes esta caro" y no solo "interes": sin tildes, "interes" también aparece en "me interesa".
    "tasa_cuota": ["cuanto queda la cuota", "interes esta caro"],
    "sin_inicial": ["inicial esta muy alta", "no tengo inicial", "sin inicial"],
    "reporte_centrales": ["centrales", "reportado", "datacredito"],
    "comparando": ["comparando", "otra marca", "otra por menos plata"],
    "consultar_familia": ["esposa", "consultar en la casa", "familia"],
    "prefiere_usada": ["usada"],
    "tiempo_entrega": ["demora la entrega", "entrega"],
    "solo_averiguando": ["solo estaba mirando", "curiosidad"],
}
CITA = [
    "visito",
    "voy en camino",
    "voy esta tarde",
    "visitar",
    "separemela",
    "pasar manana",
    "voy saliendo",
]
COTIZACION = ["enviemela", "mandemela", "mandela"]
URGENCIA = ["voy en camino", "la necesito esta semana", "necesito la moto ya"]
PAGO = {"contado": ["de contado"], "credito": ["financiada", "a credito", "credito"]}


def _contiene(texto: str, frases: list[str]) -> bool:
    return any(frase in texto for frase in frases)


def modelos_mencionados(texto: str, nombres: dict[str, str]) -> list[str]:
    """SKU de los modelos del catálogo mencionados en el texto, en orden de aparición."""
    encontrados = []
    for nombre, sku in nombres.items():
        posicion = texto.find(nombre)
        if posicion >= 0:
            encontrados.append((posicion, sku))
    vistos, orden = set(), []
    for _, sku in sorted(encontrados):
        if sku not in vistos:
            vistos.add(sku)
            orden.append(sku)
    return orden


def analizar(catalogo: pd.DataFrame | None = None) -> dict:
    """Mide longitud, respuesta del cliente, jerga de montos, cambios de modelo, objeciones y señales."""
    catalogo = catalogo if catalogo is not None else cargar_csv("catalogo_motos.csv")
    conversaciones = cargar_conversaciones()
    # Nombre completo y línea (más largos primero) -> SKU, sin tildes y en minúsculas.
    nombres = {}
    for fila in catalogo.itertuples():
        nombres[clave_texto(f"{fila.marca} {fila.linea}")] = fila.sku
    for fila in catalogo.itertuples():
        nombres.setdefault(clave_texto(fila.linea), fila.sku)
    nombres = dict(sorted(nombres.items(), key=lambda par: -len(par[0])))

    total = len(conversaciones)
    longitudes, del_cliente = [], []
    sin_respuesta = 0
    montos, cero, cambios, varias_menciones = Counter(), 0, 0, 0
    objeciones, sin_objecion = Counter(), 0
    senales = Counter()
    for conversacion in conversaciones:
        mensajes = conversacion["mensajes"]
        longitudes.append(len(mensajes))
        cliente = [clave_texto(m["texto"]) or "" for m in mensajes if m["emisor"] == "cliente"]
        del_cliente.append(len(cliente))
        # Sin respuesta: tras el saludo inicial no hay ningún mensaje del cliente (TRD 8.1).
        if not any(m["emisor"] == "cliente" for m in mensajes[1:]):
            sin_respuesta += 1
        texto = " \n ".join(cliente)
        texto_monto = " \n ".join(m["texto"] for m in mensajes if m["emisor"] == "cliente")

        for etiqueta, patron in PATRONES_MONTO.items():
            if re.search(patron, texto if "$" not in etiqueta else texto_monto):
                montos[etiqueta] += 1
        cero += bool(re.search(CERO_MILLONES, texto))

        mencionados = modelos_mencionados(texto, nombres)
        cambios += len(mencionados) > 1
        varias_menciones += len(mencionados) > 0

        encontradas = [nombre for nombre, frases in OBJECIONES.items() if _contiene(texto, frases)]
        objeciones.update(encontradas)
        sin_objecion += not encontradas
        senales["pidió cita"] += _contiene(texto, CITA)
        senales["pidió cotización"] += _contiene(texto, COTIZACION)
        senales["urgencia (intención alta)"] += _contiene(texto, URGENCIA)
        senales["pago de contado"] += _contiene(texto, PAGO["contado"])
        senales["pago a crédito o financiado"] += _contiene(texto, PAGO["credito"])

    cifras = {
        "conversaciones": total,
        "mensajes_media": mean(longitudes),
        "sin_respuesta": sin_respuesta,
        "cero_millones": cero,
        "cambios_modelo": cambios,
        "con_modelo": varias_menciones,
        "montos": dict(montos),
        "objeciones": dict(objeciones),
        "senales": dict(senales),
    }
    tabla_longitud = tabla_md(
        ["Medida", "Valor"],
        [
            ["Conversaciones", miles(total)],
            ["Mensajes por conversación (media / mediana / mín. / máx.)", f"{mean(longitudes):.1f} / {median(longitudes):g} / {min(longitudes)} / {max(longitudes)}".replace(".", ",", 1)],
            ["Mensajes del cliente por conversación (media)", f"{mean(del_cliente):.1f}".replace(".", ",")],
            ["Sin respuesta del cliente tras el saludo", f"{sin_respuesta} ({pct(sin_respuesta / total)})"],
            ["Mencionan al menos un modelo del catálogo", f"{varias_menciones} ({pct(varias_menciones / total)})"],
            ["**Cambio de modelo** (el cliente menciona 2 o más modelos)", f"{cambios} ({pct(cambios / total)})"],
            ["Dicen tener **0** millones / palos de inicial", cero],
        ],
    )  # fmt: skip
    tabla_montos = tabla_md(
        ["Forma de expresar el monto", "Conversaciones", "%"],
        [[k, v, pct(v / total)] for k, v in sorted(montos.items(), key=lambda par: -par[1])],
    )
    tabla_objeciones = tabla_md(
        ["Objeción (aprox. por palabras clave)", "Conversaciones", "%", "Palabras clave"],
        [
            [f"`{k}`", objeciones[k], pct(objeciones[k] / total), ", ".join(OBJECIONES[k])]
            for k in OBJECIONES
        ]
        + [["`ninguna` (sin palabra clave)", sin_objecion, pct(sin_objecion / total), "—"]],
    )
    tabla_senales = tabla_md(
        ["Señal (aprox. por palabras clave)", "Conversaciones", "%"],
        [[k, v, pct(v / total)] for k, v in senales.items()],
    )

    fig, eje = plt.subplots(figsize=(7, 3.5))
    etiquetas = list(OBJECIONES)
    eje.barh(etiquetas, [objeciones[k] for k in etiquetas])
    eje.invert_yaxis()
    eje.set_title("Objeciones aproximadas por palabras clave")
    eje.set_xlabel("Conversaciones")
    figura = guardar_figura(fig, "objeciones.png")

    return {
        "longitud": tabla_longitud,
        "montos": tabla_montos,
        "objeciones": tabla_objeciones,
        "senales": tabla_senales,
        "figura_objeciones": figura,
        "cifras": cifras,
    }


if __name__ == "__main__":  # diagnóstico rápido: uv run python -m eda.conversaciones
    for clave, valor in analizar()["cifras"].items():
        print(f"{clave}: {valor}")
