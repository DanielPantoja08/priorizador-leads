"""Comprueba que la base tenga aplicadas las mismas migraciones que el repositorio.

Las migraciones se aplican a mano (`supabase db push`, con `--dry-run` antes), y un cambio de
esquema puede llegar al código antes que a la base. Este control no aplica nada: compara y, si hay
diferencia, sale con código 1 para detener el pipeline o marcar el CI en rojo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from pipeline.config import RAIZ, cargar_config

DIR_MIGRACIONES = RAIZ / "supabase" / "migrations"


def versiones_del_repositorio(directorio: Path = DIR_MIGRACIONES) -> set[str]:
    """Versiones de las migraciones versionadas: el prefijo numérico de `<version>_<nombre>.sql`."""
    return {archivo.name.split("_", 1)[0] for archivo in directorio.glob("*.sql")}


def versiones_aplicadas(conn: psycopg.Connection) -> set[str]:
    """Versiones que la CLI de Supabase registró como aplicadas en la base."""
    filas = conn.execute("select version from supabase_migrations.schema_migrations").fetchall()
    return {fila[0] for fila in filas}


def diferencias(repositorio: set[str], aplicadas: set[str]) -> tuple[list[str], list[str]]:
    """(pendientes en la base, aplicadas que no están en el repositorio), ordenadas."""
    return sorted(repositorio - aplicadas), sorted(aplicadas - repositorio)


def main() -> int:
    """Imprime el resultado. Devuelve 0 si coinciden y 1 si hay diferencias."""
    with psycopg.connect(cargar_config().database_url) as conn:
        pendientes, desconocidas = diferencias(
            versiones_del_repositorio(), versiones_aplicadas(conn)
        )
    if not pendientes and not desconocidas:
        print(f"Migraciones al día: {len(versiones_del_repositorio())} aplicadas.")
        return 0
    for version in pendientes:
        print(f"Pendiente en la base: {version}", file=sys.stderr)
    for version in desconocidas:
        print(f"Aplicada en la base y ausente del repositorio: {version}", file=sys.stderr)
    print(
        "El esquema de la base no coincide con el código. Revise con `supabase db push --dry-run`"
        " y aplique con `supabase db push` antes de correr el pipeline.",
        file=sys.stderr,
    )
    return 1
