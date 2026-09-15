"""Deduplicación de leads en clientes, siempre dentro de la misma empresa (RF-04, RF-12, TRD 7)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from rapidfuzz import fuzz

from pipeline.normalize import ARCHIVO_LEADS, clave_texto
from pipeline.quality import ColectorCalidad

UMBRAL_NOMBRE = 60  # por debajo, el grupo se conserva pero se marca para revisión
_MUY_ANTIGUO = datetime.min.isoformat()


def clave_dedup(telefono: str | None, email: str | None, lead_id: str) -> str:
    """Clave natural del cliente: teléfono; si es inválido, email; si tampoco hay, el propio lead."""
    if telefono:
        return f"tel:{telefono}"
    if email:
        return f"email:{email}"
    return f"lead:{lead_id}"


def _orden_reciente(fila: dict) -> tuple[str, str]:
    """Clave para ordenar del más antiguo al más reciente; las fechas nulas cuentan como las más antiguas."""
    fecha = fila["fecha_registro"]
    return (fecha.isoformat() if fecha is not None else _MUY_ANTIGUO, fila["lead_id"])


def elegir_principal(grupo: list[dict]) -> str:
    """El lead más reciente que no esté descartado. Si todos están descartados, el más reciente."""
    activos = [f for f in grupo if f["estado_gestion"] != "Descartado"]
    return max(activos or grupo, key=_orden_reciente)["lead_id"]


def deduplicar(leads: pd.DataFrame, colector: ColectorCalidad) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Agrupa por (empresa_id, clave_dedup). Devuelve (clientes, leads con clave y es_principal).

    Todos los leads se conservan enlazados a su cliente; solo uno por cliente es principal.
    """
    df = leads.copy()
    df["clave_dedup"] = [
        clave_dedup(t, e, lid)
        for t, e, lid in zip(df["telefono"], df["email"], df["lead_id"], strict=True)
    ]
    clientes, principales = [], set()
    for (empresa, clave), grupo_df in df.groupby(["empresa_id", "clave_dedup"], sort=True):
        grupo = sorted(
            grupo_df.to_dict("records"), key=_orden_reciente
        )  # del más antiguo al más reciente

        if len(grupo) > 1:
            nombres = [clave_texto(f["nombre"]) or "" for f in grupo]
            similitud = min(
                fuzz.token_set_ratio(a, b) for i, a in enumerate(nombres) for b in nombres[i + 1 :]
            )
            if similitud < UMBRAL_NOMBRE:
                for f in grupo:
                    colector.registrar(ARCHIVO_LEADS, f["lead_id"], "nombre_cliente", "posible_colision_telefono", f["nombre"], f"similitud {similitud:.0f}; se conserva el grupo", empresa)  # fmt: skip

        principales.add(elegir_principal(grupo))
        recientes = list(reversed(grupo))
        clientes.append({
            "empresa_id": empresa,
            "clave_dedup": clave,
            "telefono": next((f["telefono"] for f in recientes if f["telefono"]), None),
            "email": next((f["email"] for f in recientes if f["email"]), None),
            # El nombre más completo del grupo; ante empate, el del lead más reciente.
            "nombre": max(recientes, key=lambda f: len(f["nombre"]))["nombre"],
            "ciudad": next((f["ciudad"] for f in recientes if f["ciudad"]), None),
            "leads": len(grupo),
            "canales": len({f["canal"] for f in grupo}),
        })  # fmt: skip
    df["es_principal"] = df["lead_id"].isin(principales)
    return pd.DataFrame(clientes, dtype="object"), df
