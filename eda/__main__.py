"""Punto de entrada del EDA: `uv run python -m eda` genera docs/EDA.md y docs/img/eda/."""

from eda import conversaciones, historico, perfil, reporte


def main() -> None:
    """Ejecuta los tres análisis y escribe el reporte."""
    resultado_perfil = perfil.analizar()
    catalogo = resultado_perfil["catalogo"]
    resultado_historico = historico.analizar(catalogo)
    resultado_conversaciones = conversaciones.analizar(catalogo)
    conteo, discrepancias = reporte.escribir(
        resultado_perfil, resultado_historico, resultado_conversaciones
    )

    print("docs/EDA.md generado.")
    print(
        f"Verificación: {conteo[reporte.SI]} coinciden, {conteo[reporte.NO]} no coinciden, {conteo[reporte.INFO]} informativas."
    )
    for fila in discrepancias:
        print(f"  - {fila[0]} -> {fila[2]}")


if __name__ == "__main__":
    main()
