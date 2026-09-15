"""Normalización del modelo de interés contra el catálogo (TRD 6.2).

Coincidencia aproximada determinística con rapidfuzz: el mismo texto siempre da el mismo resultado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
from rapidfuzz import fuzz

from pipeline.normalize import ARCHIVO_LEADS, clave_texto
from pipeline.quality import ColectorCalidad

UMBRAL_COMPLETO = 85  # contra "marca linea"
UMBRAL_LINEA = 90  # contra la línea sola


@dataclass(frozen=True)
class Coincidencia:
    """Resultado de normalizar un texto de modelo."""

    sku: str | None
    marca: str | None
    puntaje: float | None
    regla: str  # coincidencia_completa | coincidencia_linea | modelo_ambiguo | modelo_faltante | sin_coincidencia


def limpiar_modelo(texto: object) -> str | None:
    """Minúsculas, sin tildes, a.k.t -> akt, sin año (20xx) y espacios colapsados."""
    limpio = clave_texto(texto)
    if limpio is None:
        return None
    limpio = limpio.replace("a.k.t", "akt")
    limpio = re.sub(r"\b20\d{2}\b", "", limpio)
    return " ".join(limpio.split()) or None


class Catalogo:
    """Catálogo de motos con índices precalculados para la coincidencia y la disponibilidad."""

    def __init__(self, crudo: pd.DataFrame) -> None:
        self.modelos = pd.DataFrame(
            {
                "sku": crudo["sku"].str.strip(),
                "marca": crudo["marca"].str.strip(),
                "linea": crudo["linea"].str.strip(),
                "cilindraje": crudo["cilindraje"].astype(int),
                "segmento": crudo["segmento"].str.strip(),
                "precio_lista": crudo["precio_lista"].astype(int),
                "unidades_disponibles": crudo["unidades_disponibles"].astype(int),
            },
            dtype="object",
        )
        self._completos = {
            f.sku: limpiar_modelo(f"{f.marca} {f.linea}") for f in self.modelos.itertuples()
        }
        self._lineas = {f.sku: limpiar_modelo(f.linea) for f in self.modelos.itertuples()}
        self._marcas = dict(zip(self.modelos["sku"], self.modelos["marca"], strict=True))
        self.disponibilidad = {
            sku.strip(): {pv.strip() for pv in str(pvs).split("|") if pv.strip()}
            for sku, pvs in zip(crudo["sku"], crudo["puntos_venta_disponibles"], strict=True)
        }

    def _mejor_unico(
        self, limpio: str, opciones: dict[str, str], umbral: int
    ) -> tuple[str, float] | None:
        """El SKU con mayor puntaje, solo si supera el umbral y no hay empate."""
        puntajes = {sku: fuzz.token_set_ratio(limpio, texto) for sku, texto in opciones.items()}
        mejor = max(puntajes.values())
        empatados = [sku for sku, p in puntajes.items() if p == mejor]
        return (empatados[0], mejor) if mejor >= umbral and len(empatados) == 1 else None

    def resolver(self, texto: object) -> Coincidencia:
        """Aplica los pasos 1 a 5 de TRD 6.2."""
        limpio = limpiar_modelo(texto)
        if limpio is None:
            return Coincidencia(None, None, None, "modelo_faltante")
        if encontrado := self._mejor_unico(limpio, self._completos, UMBRAL_COMPLETO):
            sku, puntaje = encontrado
            return Coincidencia(sku, self._marcas[sku], puntaje, "coincidencia_completa")
        if encontrado := self._mejor_unico(limpio, self._lineas, UMBRAL_LINEA):
            sku, puntaje = encontrado
            return Coincidencia(sku, self._marcas[sku], puntaje, "coincidencia_linea")
        # Solo marca, o varias líneas empatadas (p. ej. "Bajaj Pulsar" corresponde a 3 líneas).
        puntajes_marca = {
            m: fuzz.partial_ratio(m.lower(), limpio) for m in sorted(set(self._marcas.values()))
        }
        marca = max(puntajes_marca, key=puntajes_marca.get)
        if puntajes_marca[marca] >= UMBRAL_COMPLETO:
            return Coincidencia(None, marca, puntajes_marca[marca], "modelo_ambiguo")
        return Coincidencia(None, None, None, "sin_coincidencia")

    def disponible(self, sku: str | None, punto_venta_id: str) -> bool | None:
        """True si el SKU está disponible en el punto de venta; None si no hay SKU (TRD 6.2, paso 6)."""
        return None if sku is None else punto_venta_id in self.disponibilidad.get(sku, set())


def asignar_modelos(
    leads: pd.DataFrame, catalogo: Catalogo, colector: ColectorCalidad
) -> pd.DataFrame:
    """Agrega sku_interes, marca_interes, match_modelo_score y modelo_disponible_pv a los leads."""
    resultado = leads.copy()
    skus, marcas, puntajes, disponibles = [], [], [], []
    for r in leads.itertuples(index=False):
        c = catalogo.resolver(r.modelo_texto_original)
        if c.regla in ("modelo_ambiguo", "modelo_faltante", "sin_coincidencia"):
            accion = {
                "modelo_ambiguo": f"solo marca {c.marca}",
                "modelo_faltante": "sin modelo",
                "sin_coincidencia": "sin SKU ni marca",
            }[c.regla]
            colector.registrar(ARCHIVO_LEADS, r.lead_id, "modelo_interes_texto", c.regla, r.modelo_texto_original, accion, r.empresa_id)  # fmt: skip
        skus.append(c.sku)
        marcas.append(c.marca)
        puntajes.append(c.puntaje)
        disponibles.append(catalogo.disponible(c.sku, r.punto_venta_id))
    resultado["sku_interes"] = pd.Series(skus, index=leads.index, dtype="object")
    resultado["marca_interes"] = pd.Series(marcas, index=leads.index, dtype="object")
    resultado["match_modelo_score"] = pd.Series(puntajes, index=leads.index, dtype="object")
    resultado["modelo_disponible_pv"] = pd.Series(disponibles, index=leads.index, dtype="object")
    return resultado
