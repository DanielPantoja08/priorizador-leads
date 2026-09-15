"""CLI del pipeline (TRD 11.1): `uv run python -m pipeline run` y `uv run python -m pipeline eval`.

En la Fase B, `run` ejecuta ingesta, normalización, deduplicación y carga.
Las etapas de extracción, puntaje y asignación se agregan en las fases C y D.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date

from pipeline import catalog_match, db, dedup, ingest, load, normalize
from pipeline.config import cargar_config
from pipeline.quality import ColectorCalidad


def ejecutar(fecha_corte: date | None) -> int:
    """Corre todas las etapas disponibles. Devuelve 0 si terminó bien y 1 si hubo un error."""
    config = cargar_config()
    disparador = "schedule" if os.getenv("GITHUB_EVENT_NAME") == "schedule" else "manual"
    inicio = time.perf_counter()
    with db.conectar(config.database_url) as conn:
        ejecucion_id = db.abrir_ejecucion(conn, disparador)
        conteos: dict = {}
        try:
            colector = ColectorCalidad()
            insumos = ingest.leer_insumos()
            conteos["leads_crudos"] = len(insumos.leads)

            leads = normalize.normalizar_leads(insumos.leads, colector)
            catalogo = catalog_match.Catalogo(insumos.catalogo)
            leads = catalog_match.asignar_modelos(leads, catalogo, colector)
            normalize.validar_conversaciones(leads, insumos.conversaciones, colector)
            clientes, leads = dedup.deduplicar(leads, colector)
            asesores = normalize.normalizar_asesores(insumos.asesores)
            historico = normalize.normalizar_historico(insumos.historico)

            # Fecha de corte: argumento, variable FECHA_CORTE o la última fecha de registro.
            registros = [f for f in leads["fecha_registro"] if f is not None]
            corte = fecha_corte or config.fecha_corte or max(registros).date()

            conteos.update(load.cargar_referencia(conn, leads, asesores, catalogo))
            conteos["historico_cierre"] = load.cargar_historico(conn, historico)
            conteos.update(load.cargar_clientes_y_leads(conn, clientes, leads, colector))
            conteos.update(load.cargar_conversaciones(conn, insumos.conversaciones, leads))
            conteos["problema_calidad"] = load.reemplazar_problemas(conn, ejecucion_id, colector)
            conteos["duracion_s"] = round(time.perf_counter() - inicio, 1)

            db.cerrar_ejecucion(conn, ejecucion_id, "ok", corte, conteos)
        except Exception as error:  # la corrida queda registrada como error y sale con código 1
            conn.rollback()
            db.cerrar_ejecucion(conn, ejecucion_id, "error", None, conteos, repr(error))
            print(f"Ejecución {ejecucion_id} con error: {error!r}", file=sys.stderr)
            return 1

    print(f"Ejecución {ejecucion_id} ok · fecha de corte {corte} · {conteos['duracion_s']} s")
    for tabla, n in conteos.items():
        print(f"  {tabla}: {n}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m pipeline")
    comandos = parser.add_subparsers(dest="comando", required=True)
    run = comandos.add_parser("run", help="ejecuta el flujo completo")
    run.add_argument("--fecha-corte", type=date.fromisoformat, default=None, help="YYYY-MM-DD")
    run.add_argument(
        "--extractor", choices=["gemini", "reglas"], default=None, help="se usa desde la Fase C"
    )
    comandos.add_parser("eval", help="evaluaciones (Fase C y D)")
    args = parser.parse_args()

    if args.comando == "run":
        if args.extractor:
            os.environ["EXTRACTOR"] = args.extractor
        sys.exit(ejecutar(args.fecha_corte))
    print("El comando eval se implementa en la Fase C.", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
