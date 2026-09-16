"""CLI del pipeline (TRD 11.1): `uv run python -m pipeline run` y `uv run python -m pipeline eval`.

`run` ejecuta la cadena completa: ingesta, normalización, deduplicación, carga, extracción con IA,
puntaje y asignación. Todas las etapas son idempotentes (RNF-03).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date

from pipeline import assign, catalog_match, db, dedup, ingest, load, normalize, scoring
from pipeline.config import cargar_config
from pipeline.extract import etapa as etapa_extraccion
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

            # Extracción: necesita las conversaciones ya cargadas por la llave foránea.
            senales, conteos_extraccion = etapa_extraccion.ejecutar(
                conn, config, insumos.conversaciones, leads, catalogo, colector
            )
            conteos.update(conteos_extraccion)

            # Las señales consolidadas se persisten para que la app muestre lo mismo que se puntuó.
            conteos["senales_lead"] = load.cargar_senales(conn, senales, leads, catalogo)

            # Puntaje y asignación (TRD 9 y 10). Las horas de urgencia se miden contra el último
            # registro del día de corte, no contra el reloj: así la corrida es reproducible.
            precios = dict(
                zip(catalogo.modelos["sku"], catalogo.modelos["precio_lista"], strict=True)
            )
            momento = scoring.momento_corte(leads, corte)
            puntajes = scoring.calcular(leads, senales, precios, momento, config.ventana_dias)
            conteos["score"] = load.cargar_score(conn, puntajes, corte)
            conteos.update(load.cargar_asignacion(conn, assign.asignar(puntajes, asesores), corte))

            conteos["problema_calidad"] = load.reemplazar_problemas(conn, ejecucion_id, colector)
            conteos["duracion_s"] = round(time.perf_counter() - inicio, 1)

            # Si alguna conversación la resolvió el respaldo, la corrida lo declara (TRD 8.2).
            estado = "ok_con_respaldo" if conteos.get("extraccion_respaldo") else "ok"
            db.cerrar_ejecucion(
                conn,
                ejecucion_id,
                estado,
                corte,
                conteos,
                llamadas_llm=conteos.get("llamadas_llm", 0),
                errores_llm=conteos.get("errores_llm", 0),
            )
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
    evaluacion = comandos.add_parser("eval", help="evalúa la extracción contra el gold (TRD 8.5)")
    evaluacion.add_argument(
        "--con-gemini",
        action="store_true",
        help="además de la línea base por reglas, evalúa con Gemini (consume cuota)",
    )
    comandos.add_parser("validate-scoring", help="valida el puntaje contra el histórico (TRD 9.3)")
    args = parser.parse_args()

    if args.comando == "run":
        if args.extractor:
            os.environ["EXTRACTOR"] = args.extractor
        sys.exit(ejecutar(args.fecha_corte))

    if args.comando == "validate-scoring":
        from evaluation.validate_scoring import main as validar_puntaje

        sys.exit(validar_puntaje())

    # eval: compara los extractores contra el conjunto de referencia revisado (TRD 8.5).
    from evaluation.eval_extraction import main as evaluar_extraccion

    sys.exit(evaluar_extraccion(con_gemini=args.con_gemini))


if __name__ == "__main__":
    main()
