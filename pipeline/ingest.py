"""Ingesta de los cinco insumos de data/raw (RF-01). Lee todo como texto para no perder formatos."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from pipeline.config import DIR_RAW

# Columnas mínimas esperadas por archivo: si falta alguna, la corrida se detiene con un error claro.
COLUMNAS = {
    "leads.csv": {
        "lead_id", "fecha_registro", "canal", "empresa_id", "punto_venta_id", "nombre_cliente",
        "telefono", "email", "ciudad", "modelo_interes_texto", "estado_gestion",
        "fecha_primer_contacto", "campania",
    },
    "catalogo_motos.csv": {
        "sku", "marca", "linea", "cilindraje", "segmento", "precio_lista",
        "puntos_venta_disponibles", "unidades_disponibles",
    },
    "asesores.csv": {
        "asesor_id", "nombre", "punto_venta_id", "empresa_id", "capacidad_diaria_leads",
        "activo", "fecha_ingreso",
    },
    "historico_cierres.csv": {
        "lead_id", "fecha_registro", "canal", "empresa_id", "punto_venta_id", "modelo_cotizado",
        "precio_lista", "horas_al_primer_contacto", "numero_contactos", "manifesto_cuota_inicial",
        "forma_pago_declarada", "pidio_cita", "desenlace",
    },
}  # fmt: skip


@dataclass
class Insumos:
    """Los cinco archivos tal como vienen."""

    leads: pd.DataFrame
    catalogo: pd.DataFrame
    asesores: pd.DataFrame
    historico: pd.DataFrame
    conversaciones: list[dict]


def leer_csv(nombre: str, dir_raw: Path = DIR_RAW) -> pd.DataFrame:
    """Lee un CSV como texto (vacíos -> NaN) y valida sus columnas."""
    df = pd.read_csv(dir_raw / nombre, dtype="str", encoding="utf-8")
    faltantes = COLUMNAS[nombre] - set(df.columns)
    if faltantes:
        raise ValueError(f"{nombre}: faltan columnas {sorted(faltantes)}")
    return df


def leer_conversaciones(dir_raw: Path = DIR_RAW) -> list[dict]:
    """Lee conversaciones.json y valida la estructura mínima de cada objeto."""
    with open(dir_raw / "conversaciones.json", encoding="utf-8") as archivo:
        conversaciones = json.load(archivo)
    for c in conversaciones:
        if not {"conversacion_id", "lead_id", "fecha_inicio", "mensajes"} <= c.keys():
            raise ValueError(f"conversaciones.json: objeto incompleto {c.get('conversacion_id')}")
    return conversaciones


def leer_insumos(dir_raw: Path = DIR_RAW) -> Insumos:
    """Lee los cinco insumos sin intervención manual."""
    return Insumos(
        leads=leer_csv("leads.csv", dir_raw),
        catalogo=leer_csv("catalogo_motos.csv", dir_raw),
        asesores=leer_csv("asesores.csv", dir_raw),
        historico=leer_csv("historico_cierres.csv", dir_raw),
        conversaciones=leer_conversaciones(dir_raw),
    )


def hash_mensajes(mensajes: list[dict]) -> str:
    """sha256 del contenido de los mensajes: cambia solo si cambia la conversación (clave de caché)."""
    canonico = json.dumps(mensajes, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()
