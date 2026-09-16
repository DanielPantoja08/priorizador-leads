"""Reparto de los leads del día entre los asesores del punto de venta (RF-08, TRD 10).

El reparto es en serpentina: con los leads ya ordenados por prioridad, el primero va al asesor A,
el segundo al B, el tercero al C, el cuarto otra vez al C, y así. Si se repartiera siempre en el
mismo sentido, el primer asesor se quedaría con todos los mejores leads del día.

La asignación nunca cruza el punto de venta ni la empresa, y un asesor deja de recibir en cuanto
llega a su `capacidad_diaria`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pipeline.scoring import Puntaje


@dataclass(frozen=True)
class Asignacion:
    """Un lead en la lista de un asesor, o sin cupo si nadie tenía capacidad."""

    lead_id: str
    empresa_id: str
    asesor_id: str | None
    orden: int | None
    estado: str  # 'asignado' o 'sin_cupo'
    prioritario: bool


def _asesores_de(asesores: pd.DataFrame, punto_venta_id: str) -> list[dict]:
    """Asesores activos del punto de venta, en orden estable por identificador."""
    activos = asesores[asesores["activo"] & asesores["punto_venta_id"].eq(punto_venta_id)]
    return sorted(activos.to_dict("records"), key=lambda a: a["asesor_id"])


def _serpentina(cupos: list[str]) -> list[str]:
    """Recorre la lista de ida y de vuelta sin repetir los extremos: A B C C B A A B C..."""
    if not cupos:
        return []
    vuelta = list(cupos) + list(reversed(cupos))
    return vuelta


def repartir(puntajes: list[Puntaje], asesores: list[dict]) -> list[Asignacion]:
    """Reparte en serpentina respetando la capacidad de cada asesor.

    `puntajes` ya viene ordenado por prioridad. Devuelve una asignación por lead, incluidos los
    que quedaron sin cupo.
    """
    capacidad = {a["asesor_id"]: int(a["capacidad_diaria"]) for a in asesores}
    asignados: dict[str, int] = {a["asesor_id"]: 0 for a in asesores}
    ciclo = _serpentina([a["asesor_id"] for a in asesores])

    resultado, posicion = [], 0
    for puntaje in puntajes:
        asesor = None
        # Avanza por la serpentina hasta encontrar un asesor con cupo; si nadie tiene, sin cupo.
        for _ in range(len(ciclo)) if ciclo else ():
            candidato = ciclo[posicion % len(ciclo)]
            posicion += 1
            if asignados[candidato] < capacidad[candidato]:
                asesor = candidato
                break

        if asesor is None:
            resultado.append(
                Asignacion(
                    lead_id=puntaje.lead_id,
                    empresa_id=puntaje.empresa_id,
                    asesor_id=None,
                    orden=None,
                    estado="sin_cupo",
                    prioritario=puntaje.prioritario,
                )
            )
            continue

        asignados[asesor] += 1
        resultado.append(
            Asignacion(
                lead_id=puntaje.lead_id,
                empresa_id=puntaje.empresa_id,
                asesor_id=asesor,
                orden=asignados[asesor],  # posición dentro de la lista de ese asesor
                estado="asignado",
                prioritario=puntaje.prioritario,
            )
        )
    return resultado


def asignar(puntajes: list[Puntaje], asesores: pd.DataFrame) -> list[Asignacion]:
    """Reparte todos los leads, punto de venta por punto de venta (TRD 10)."""
    por_punto: dict[str, list[Puntaje]] = {}
    for puntaje in puntajes:  # `puntajes` ya está ordenado, así que cada grupo hereda ese orden
        por_punto.setdefault(puntaje.punto_venta_id, []).append(puntaje)

    resultado = []
    for punto_venta_id in sorted(por_punto):
        resultado.extend(
            repartir(por_punto[punto_venta_id], _asesores_de(asesores, punto_venta_id))
        )
    return resultado
