"""Carga idempotente en la base (etapa load, TRD 1.2). Cada bloque corre en su propia transacción."""

from __future__ import annotations

from collections import Counter
from datetime import date

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from pipeline import db
from pipeline.catalog_match import Catalogo
from pipeline.extract.schema import Extraccion
from pipeline.ingest import hash_mensajes
from pipeline.normalize import a_bogota, hora_mensaje, resolver_fecha
from pipeline.quality import ColectorCalidad
from pipeline.scoring import VERSION_SCORE


def cargar_referencia(
    conn: psycopg.Connection, leads: pd.DataFrame, asesores: pd.DataFrame, catalogo: Catalogo
) -> dict:
    """Puntos de venta, asesores, modelos y disponibilidad por punto de venta."""
    # Ciudad del punto de venta: la más frecuente entre sus leads (empate: orden alfabético).
    ciudades = {}
    for pv, grupo in leads.groupby("punto_venta_id"):
        conteo = Counter(c for c in grupo["ciudad"] if c)
        ciudades[pv] = min(conteo, key=lambda c: (-conteo[c], c)) if conteo else None
    empresas_pv = dict(zip(leads["punto_venta_id"], leads["empresa_id"], strict=True))
    empresas_pv.update(zip(asesores["punto_venta_id"], asesores["empresa_id"], strict=True))
    puntos = [
        {"punto_venta_id": pv, "empresa_id": emp, "ciudad": ciudades.get(pv)}
        for pv, emp in sorted(empresas_pv.items())
    ]
    modelos_pv = [
        {"sku": sku, "punto_venta_id": pv}
        for sku, pvs in sorted(catalogo.disponibilidad.items())
        for pv in sorted(pvs)
    ]
    with conn.transaction(), conn.cursor() as cur:
        conteos = {
            "punto_venta": db.upsert(cur, "punto_venta", puntos, ["punto_venta_id"]),
            "asesor": db.upsert(cur, "asesor", asesores.to_dict("records"), ["asesor_id"]),
            "modelo": db.upsert(cur, "modelo", catalogo.modelos.to_dict("records"), ["sku"]),
            "modelo_punto_venta": db.upsert(
                cur, "modelo_punto_venta", modelos_pv, ["sku", "punto_venta_id"]
            ),
        }
        # Disponibilidad que ya no está en el catálogo.
        cur.execute(
            "delete from public.modelo_punto_venta where (sku, punto_venta_id) not in "
            "(select * from unnest(%s::text[], %s::text[]))",
            ([m["sku"] for m in modelos_pv], [m["punto_venta_id"] for m in modelos_pv]),
        )
    return conteos


def cargar_historico(conn: psycopg.Connection, historico: pd.DataFrame) -> int:
    """Histórico de cierres, por lead_id."""
    with conn.transaction(), conn.cursor() as cur:
        return db.upsert(cur, "historico_cierre", historico.to_dict("records"), ["lead_id"])


def cargar_clientes_y_leads(
    conn: psycopg.Connection, clientes: pd.DataFrame, leads: pd.DataFrame, colector: ColectorCalidad
) -> dict:
    """Clientes por (empresa_id, clave_dedup) y leads enlazados a su cliente, con sus banderas de calidad."""
    columnas_cliente = ["empresa_id", "clave_dedup", "telefono", "email", "nombre", "ciudad"]
    columnas_lead = [
        "lead_id", "empresa_id", "punto_venta_id", "canal", "campania", "fecha_registro",
        "fecha_registro_precision", "fecha_primer_contacto", "fecha_contacto_precision",
        "estado_gestion", "modelo_texto_original", "sku_interes", "marca_interes",
        "match_modelo_score", "modelo_disponible_pv", "es_principal",
    ]  # fmt: skip
    with conn.transaction(), conn.cursor() as cur:
        n_clientes = db.upsert(
            cur,
            "cliente",
            clientes[columnas_cliente].to_dict("records"),
            ["empresa_id", "clave_dedup"],
        )
        # El cliente_id lo genera la base; se recupera por la clave natural.
        cur.execute("select empresa_id, clave_dedup, cliente_id from public.cliente")
        ids = {(empresa, clave): cid for empresa, clave, cid in cur.fetchall()}
        filas = []
        for fila in leads[columnas_lead + ["clave_dedup"]].to_dict("records"):
            fila["cliente_id"] = ids[(fila["empresa_id"], fila.pop("clave_dedup"))]
            fila["flags_calidad"] = colector.banderas_de(fila["lead_id"])
            filas.append(fila)
        n_leads = db.upsert(cur, "lead", filas, ["lead_id"])
        # Clientes que quedaron sin leads (p. ej. si cambió la clave de un lead en los insumos).
        cur.execute(
            "delete from public.cliente c where not exists (select 1 from public.lead l where l.cliente_id = c.cliente_id)"
        )
    return {"cliente": n_clientes, "lead": n_leads}


def cargar_conversaciones(
    conn: psycopg.Connection, conversaciones: list[dict], leads: pd.DataFrame
) -> dict:
    """Conversaciones (las huérfanas sin empresa) y sus mensajes."""
    empresas = dict(zip(leads["lead_id"], leads["empresa_id"], strict=True))
    filas_conv, filas_msj = [], []
    for c in conversaciones:
        lead_id = c["lead_id"] if c["lead_id"] in empresas else None
        filas_conv.append({
            "conversacion_id": c["conversacion_id"],
            "lead_id_origen": c["lead_id"],
            "lead_id": lead_id,
            "empresa_id": empresas.get(lead_id),
            "fecha_inicio": a_bogota(resolver_fecha(c["fecha_inicio"], None, es_registro=False)[0]),
            "hash_contenido": hash_mensajes(c["mensajes"]),
            "es_huerfana": lead_id is None,
        })  # fmt: skip
        for orden, m in enumerate(c["mensajes"], start=1):
            filas_msj.append({
                "conversacion_id": c["conversacion_id"],
                "orden": orden,
                "emisor": m.get("emisor"),
                "hora": hora_mensaje(m.get("hora")),
                "texto": m.get("texto"),
            })  # fmt: skip
    with conn.transaction(), conn.cursor() as cur:
        n_conv = db.upsert(cur, "conversacion", filas_conv, ["conversacion_id"])
        # Los mensajes se reemplazan completos: si una conversación se acorta, no quedan mensajes viejos.
        cur.execute(
            "delete from public.mensaje where conversacion_id = any(%s)",
            ([f["conversacion_id"] for f in filas_conv],),
        )
        n_msj = db.upsert(cur, "mensaje", filas_msj, ["conversacion_id", "orden"])
    return {"conversacion": n_conv, "mensaje": n_msj}


CAMPOS_CACHE = (
    "conversacion_id", "modelo_texto", "cuota_inicial_cop", "menciona_cuota", "forma_pago",
    "intencion", "objecion", "pidio_cita", "pidio_cotizacion", "cliente_respondio", "evidencia",
)  # fmt: skip


def extracciones_cacheadas(
    conn: psycopg.Connection, extractor: str, version: str
) -> dict[str, Extraccion]:
    """Extracciones ya calculadas para ese extractor y versión, por `hash_contenido` (TRD 8.2).

    Cambiar el prompt sube la versión, así que la caché anterior deja de usarse sin borrarla.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"select hash_contenido, {', '.join(CAMPOS_CACHE)} from public.extraccion "
            "where extractor = %s and prompt_version = %s",
            (extractor, version),
        )
        filas = cur.fetchall()
    cache = {}
    for fila in filas:
        datos = dict(zip(("hash_contenido", *CAMPOS_CACHE), fila, strict=True))
        huella = datos.pop("hash_contenido")
        # Los nulos de la base se descartan para que el modelo use sus valores por defecto.
        cache[huella] = Extraccion(**{k: v for k, v in datos.items() if v is not None})
    return cache


def cargar_extracciones(conn: psycopg.Connection, filas: list[dict]) -> int:
    """Guarda las extracciones por su clave de caché (hash_contenido, extractor, prompt_version)."""
    with conn.transaction(), conn.cursor() as cur:
        return db.upsert(
            cur, "extraccion", filas, ["hash_contenido", "extractor", "prompt_version"]
        )


def cargar_score(conn: psycopg.Connection, puntajes: list, fecha_corte: date) -> int:
    """Guarda el puntaje de cada lead para esa fecha de corte y versión (TRD 9.2).

    La clave primaria es (lead_id, fecha_corte, version_score), así que volver a correr la misma
    fecha reescribe las mismas filas: el resultado no depende de cuántas veces se ejecute.
    """
    filas = [
        {
            "lead_id": p.lead_id,
            "fecha_corte": fecha_corte,
            "version_score": VERSION_SCORE,
            "empresa_id": p.empresa_id,
            "puntos_calidad": p.puntos_calidad,
            "puntos_conversacion": p.puntos_conversacion,
            "puntos_urgencia": p.puntos_urgencia,
            "prioridad": p.prioridad,
            "temperatura": p.temperatura,
            # `razones` es una lista de objetos: se envía como jsonb, no como arreglo de Postgres.
            "razones": Jsonb(p.razones),
        }
        for p in puntajes
    ]
    with conn.transaction(), conn.cursor() as cur:
        return db.upsert(cur, "score", filas, ["lead_id", "fecha_corte", "version_score"])


def cargar_asignacion(conn: psycopg.Connection, asignaciones: list, fecha_corte: date) -> dict:
    """Reemplaza por completo la asignación de esa fecha de corte (TRD 10).

    Se borra y se reinserta dentro de una misma transacción: si el reparto cambia porque cambió
    la capacidad o llegaron leads nuevos, no pueden quedar restos del reparto anterior.
    """
    filas = [
        {
            "fecha_corte": fecha_corte,
            "lead_id": a.lead_id,
            "empresa_id": a.empresa_id,
            "asesor_id": a.asesor_id,
            "orden": a.orden,
            "estado": a.estado,
            "prioritario": a.prioritario,
        }
        for a in asignaciones
    ]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("delete from public.asignacion where fecha_corte = %s", (fecha_corte,))
        db.upsert(cur, "asignacion", filas, ["fecha_corte", "lead_id"])
    return {
        "asignacion": len(filas),
        "asignacion_asignados": sum(1 for a in asignaciones if a.estado == "asignado"),
        "asignacion_sin_cupo": sum(1 for a in asignaciones if a.estado == "sin_cupo"),
        "asignacion_prioritarios": sum(1 for a in asignaciones if a.prioritario),
    }


def reemplazar_problemas(
    conn: psycopg.Connection, ejecucion_id: int, colector: ColectorCalidad
) -> int:
    """Deja en problema_calidad solo los problemas de esta corrida (así no se duplican entre corridas)."""
    filas = [
        {
            "ejecucion_id": ejecucion_id,
            "empresa_id": p.empresa_id,
            "archivo": p.archivo,
            "registro_id": p.registro_id,
            "campo": p.campo,
            "tipo": p.tipo,
            "valor_original": p.valor_original,
            "accion": p.accion,
        }
        for p in colector.problemas
    ]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("delete from public.problema_calidad")
        if filas:
            cur.executemany(
                """
                insert into public.problema_calidad
                  (ejecucion_id, empresa_id, archivo, registro_id, campo, tipo, valor_original, accion)
                values (%(ejecucion_id)s, %(empresa_id)s, %(archivo)s, %(registro_id)s, %(campo)s,
                        %(tipo)s, %(valor_original)s, %(accion)s)
                """,
                filas,
            )
    return len(filas)
