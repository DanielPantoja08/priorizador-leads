"""Pruebas del control de migraciones pendientes (sin base de datos)."""

from pipeline.migraciones import DIR_MIGRACIONES, diferencias, versiones_del_repositorio


def test_versiones_del_repositorio_toma_el_prefijo(tmp_path):
    (tmp_path / "20260101000000_esquema.sql").write_text("select 1;")
    (tmp_path / "20260102000000_rls_por_empresa.sql").write_text("select 1;")
    (tmp_path / "notas.txt").write_text("no es migración")
    assert versiones_del_repositorio(tmp_path) == {"20260101000000", "20260102000000"}


def test_las_migraciones_versionadas_tienen_version_numerica():
    versiones = versiones_del_repositorio(DIR_MIGRACIONES)
    assert versiones
    assert all(v.isdigit() and len(v) == 14 for v in versiones)


def test_diferencias_separa_pendientes_y_desconocidas():
    pendientes, desconocidas = diferencias({"1", "2", "3"}, {"1", "4"})
    assert pendientes == ["2", "3"]
    assert desconocidas == ["4"]


def test_sin_diferencias():
    assert diferencias({"1", "2"}, {"2", "1"}) == ([], [])
