"""Pruebas de las funciones puras de la app (TRD 13).

Solo se prueba lo que no toca la red ni Streamlit: el formato de la tabla que ve el asesor y los
dos ayudantes de presentación. El aislamiento se prueba contra la base en `test_aislamiento.py`,
porque es la base la que lo garantiza.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.streamlit_app import horas_desde, pesos, tabla_de

CORTE = date(2026, 9, 10)


def fila(**cambios) -> dict:
    """Una fila de `v_mis_leads_hoy` con lo mínimo que la tabla necesita."""
    base = {
        "asesor_id": "AS-001",
        "orden": 1,
        "temperatura": "Caliente",
        "prioridad": 8,
        "nombre": "Carlos Mario",
        "telefono": "3001234567",
        "canal": "WhatsApp",
        "modelo": "Boxer CT 100",
        "ia_modelo": "Bajaj Boxer CT 100",
        "ia_cuota_inicial_cop": 2_000_000,
        "ia_forma_pago": "credito",
        "fecha_registro": "2026-09-10T08:00:00-05:00",
        "estado_gestion": "Sin gestión",
    }
    return base | cambios


def marco(*filas: dict) -> pd.DataFrame:
    # dtype="object" conserva los None en vez de convertirlos en NaN.
    return pd.DataFrame(list(filas), dtype="object")


# --------------------------------------------------------------------------------------
# Ayudantes de formato
# --------------------------------------------------------------------------------------


def test_los_pesos_se_escriben_con_puntos_de_miles() -> None:
    assert pesos(10_500_000) == "$10.500.000"
    assert pesos(0) == "$0"


@pytest.mark.parametrize("vacio", [None, float("nan"), pd.NA])
def test_sin_cifra_se_muestra_una_raya(vacio: object) -> None:
    # La app nunca escribe "$0" cuando el dato falta: sería una cifra inventada.
    assert pesos(vacio) == "—"


def test_las_horas_se_cuentan_hasta_el_final_del_dia_de_corte() -> None:
    # Un lead registrado a las 8:00 del día de corte lleva casi 16 horas a la medianoche.
    assert horas_desde("2026-09-10T08:00:00-05:00", CORTE) == pytest.approx(16.0, abs=0.01)


def test_un_lead_de_ayer_acumula_un_dia_mas() -> None:
    assert horas_desde("2026-09-09T08:00:00-05:00", CORTE) == pytest.approx(40.0, abs=0.01)


def test_sin_fecha_no_hay_horas() -> None:
    assert horas_desde(None, CORTE) is None


# --------------------------------------------------------------------------------------
# tabla_de
# --------------------------------------------------------------------------------------


def test_la_lista_del_asesor_empieza_por_su_posicion() -> None:
    tabla = tabla_de(marco(fila(orden=1), fila(orden=2)), CORTE)
    assert list(tabla.columns)[0] == "#"
    assert list(tabla["#"]) == [1, 2]


def test_el_orden_es_entero_aunque_haya_leads_sin_cupo() -> None:
    # Con un nulo, pandas promovía la columna a float y el selector mostraba «1.0.».
    tabla = tabla_de(marco(fila(orden=1), fila(orden=None)), CORTE)
    assert tabla["#"].dtype == "Int64"
    assert tabla["#"][0] == 1 and pd.isna(tabla["#"][1])


def test_en_la_vista_de_empresa_se_muestra_el_asesor_y_no_la_posicion() -> None:
    # `orden` es la posición dentro de la lista de cada asesor: comparado entre asesores no
    # significa nada, así que ahí la primera columna es de quién es el lead.
    tabla = tabla_de(marco(fila(), fila(asesor_id="AS-002")), CORTE, con_asesor=True)
    assert list(tabla.columns)[0] == "Asesor"
    assert "#" not in tabla.columns
    assert list(tabla["Asesor"]) == ["AS-001", "AS-002"]


def test_un_lead_sin_cupo_se_marca_en_la_columna_del_asesor() -> None:
    tabla = tabla_de(marco(fila(asesor_id=None)), CORTE, con_asesor=True)
    assert tabla["Asesor"][0] == "sin cupo"


def test_el_modelo_de_la_ia_manda_sobre_el_del_formulario() -> None:
    # Lo que el cliente dijo en WhatsApp es mejor dato que lo que quedó en el formulario.
    tabla = tabla_de(marco(fila()), CORTE)
    assert tabla["Modelo de interés"][0] == "Bajaj Boxer CT 100"


def test_sin_conversacion_se_cae_al_modelo_del_formulario() -> None:
    tabla = tabla_de(marco(fila(ia_modelo=None)), CORTE)
    assert tabla["Modelo de interés"][0] == "Boxer CT 100"


def test_sin_modelo_por_ningun_lado_queda_una_raya() -> None:
    tabla = tabla_de(marco(fila(ia_modelo=None, modelo=None)), CORTE)
    assert tabla["Modelo de interés"][0] == "—"


def test_la_forma_de_pago_se_muestra_en_español() -> None:
    assert tabla_de(marco(fila(ia_forma_pago="credito")), CORTE)["Pago"][0] == "Crédito"
    assert tabla_de(marco(fila(ia_forma_pago="no_informa")), CORTE)["Pago"][0] == "No informa"


def test_la_temperatura_lleva_texto_y_no_solo_color() -> None:
    # El color acompaña, nunca es la única señal: hay que poder leerla sin distinguir colores.
    assert "Caliente" in tabla_de(marco(fila()), CORTE)["Temp."][0]


def test_un_telefono_ausente_no_rompe_la_tabla() -> None:
    assert tabla_de(marco(fila(telefono=None)), CORTE)["Teléfono"][0] == "—"
