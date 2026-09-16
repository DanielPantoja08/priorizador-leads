"""Pruebas del reparto en serpentina (TRD 10): capacidad, sin cupo y aislamiento por punto de venta."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from pipeline.assign import asignar, repartir
from pipeline.scoring import Puntaje


def puntaje(lead_id: str, prioridad: int = 5, punto_venta_id: str = "PV-001", **cambios) -> Puntaje:
    """Un puntaje mínimo: al reparto solo le importan el orden, el punto de venta y la marca."""
    base = {
        "lead_id": lead_id,
        "empresa_id": "EMP-01",
        "punto_venta_id": punto_venta_id,
        "puntos_calidad": prioridad,
        "puntos_conversacion": 0,
        "puntos_urgencia": 0,
        "prioridad": prioridad,
        "temperatura": "Tibio",
        "razones": [],
        "fecha_registro": datetime(2026, 9, 10),
        "sin_contacto_reciente": False,
    }
    return Puntaje(**(base | cambios))


def asesor(
    asesor_id: str, capacidad: int = 10, activo: bool = True, punto_venta_id: str = "PV-001"
) -> dict:
    return {
        "asesor_id": asesor_id,
        "empresa_id": "EMP-01",
        "punto_venta_id": punto_venta_id,
        "nombre": asesor_id,
        "capacidad_diaria": capacidad,
        "activo": activo,
    }


def test_serpentina_reparte_de_ida_y_de_vuelta() -> None:
    leads = [puntaje(f"LEAD-{i}") for i in range(6)]
    asesores = [asesor("AS-001"), asesor("AS-002"), asesor("AS-003")]
    resultado = [a.asesor_id for a in repartir(leads, asesores)]
    assert resultado == ["AS-001", "AS-002", "AS-003", "AS-003", "AS-002", "AS-001"]


def test_la_serpentina_continua_en_la_siguiente_vuelta() -> None:
    # Tras A B C C B A vuelve a empezar por A, para que nadie acumule dos veces seguidas el mejor.
    leads = [puntaje(f"LEAD-{i}") for i in range(8)]
    asesores = [asesor("AS-001"), asesor("AS-002"), asesor("AS-003")]
    resultado = [a.asesor_id for a in repartir(leads, asesores)]
    assert resultado[6:] == ["AS-001", "AS-002"]


def test_el_orden_es_la_posicion_dentro_de_la_lista_del_asesor() -> None:
    leads = [puntaje(f"LEAD-{i}") for i in range(4)]
    resultado = repartir(leads, [asesor("AS-001"), asesor("AS-002")])
    por_asesor: dict[str, list[int]] = {}
    for a in resultado:
        por_asesor.setdefault(a.asesor_id, []).append(a.orden)
    assert por_asesor == {"AS-001": [1, 2], "AS-002": [1, 2]}


def test_un_asesor_lleno_sale_del_reparto() -> None:
    leads = [puntaje(f"LEAD-{i}") for i in range(5)]
    resultado = repartir(leads, [asesor("AS-001", capacidad=1), asesor("AS-002", capacidad=10)])
    asignados = [a.asesor_id for a in resultado]
    assert asignados.count("AS-001") == 1
    assert asignados.count("AS-002") == 4


def test_los_que_no_caben_quedan_sin_cupo() -> None:
    leads = [puntaje(f"LEAD-{i}") for i in range(5)]
    resultado = repartir(leads, [asesor("AS-001", capacidad=2)])
    assert [a.estado for a in resultado] == [
        "asignado",
        "asignado",
        "sin_cupo",
        "sin_cupo",
        "sin_cupo",
    ]
    sin_cupo = [a for a in resultado if a.estado == "sin_cupo"]
    assert all(a.asesor_id is None and a.orden is None for a in sin_cupo)


def test_los_mejores_leads_se_asignan_primero() -> None:
    # El reparto respeta el orden que trae el puntaje: los de más prioridad entran antes de que
    # se agote la capacidad.
    leads = [puntaje("LEAD-BUENO", prioridad=9), puntaje("LEAD-MALO", prioridad=1)]
    resultado = repartir(leads, [asesor("AS-001", capacidad=1)])
    assert resultado[0].lead_id == "LEAD-BUENO" and resultado[0].estado == "asignado"
    assert resultado[1].lead_id == "LEAD-MALO" and resultado[1].estado == "sin_cupo"


def test_sin_asesores_activos_todo_queda_sin_cupo() -> None:
    leads = [puntaje("LEAD-1")]
    resultado = repartir(leads, [])
    assert resultado[0].estado == "sin_cupo"


def test_no_se_reparte_entre_puntos_de_venta() -> None:
    leads = [puntaje("LEAD-A", punto_venta_id="PV-001"), puntaje("LEAD-B", punto_venta_id="PV-002")]
    asesores = pd.DataFrame(
        [asesor("AS-001", punto_venta_id="PV-001"), asesor("AS-002", punto_venta_id="PV-002")],
        dtype="object",
    )
    por_lead = {a.lead_id: a.asesor_id for a in asignar(leads, asesores)}
    assert por_lead == {"LEAD-A": "AS-001", "LEAD-B": "AS-002"}


def test_los_asesores_inactivos_no_reciben_leads() -> None:
    leads = [puntaje("LEAD-1")]
    asesores = pd.DataFrame(
        [asesor("AS-001", activo=False), asesor("AS-002", activo=True)], dtype="object"
    )
    assert asignar(leads, asesores)[0].asesor_id == "AS-002"


def test_la_marca_de_prioritario_viaja_pero_no_cambia_el_reparto() -> None:
    # TRD 10: el prioritario sin cupo se resalta en el tablero, pero no se adelanta en la fila.
    leads = [puntaje("LEAD-1"), puntaje("LEAD-2", temperatura="Caliente")]
    resultado = repartir(leads, [asesor("AS-001", capacidad=1)])
    assert resultado[0].lead_id == "LEAD-1" and resultado[0].estado == "asignado"
    assert resultado[1].estado == "sin_cupo" and resultado[1].prioritario is True
