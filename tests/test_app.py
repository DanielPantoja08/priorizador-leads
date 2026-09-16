"""Pruebas de las funciones puras de la app (TRD 13).

Solo se prueba lo que no toca la red ni Streamlit: el formato de la tabla que ve el asesor y los
dos ayudantes de presentación. El aislamiento se prueba contra la base en `test_aislamiento.py`,
porque es la base la que lo garantiza.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from app.streamlit_app import frase_de_apertura, horas_desde, pesos, tabla_de

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
        "modelo_texto_original": "boxer ct100",
        "ia_conversaciones": 1,
        "ia_modelo": "Bajaj Boxer CT 100",
        "ia_modelo_texto": "boxer",
        "ia_cuota_inicial_cop": 2_000_000,
        "ia_forma_pago": "credito",
        "ia_objecion": "ninguna",
        "ia_pidio_cita": True,
        "ia_pidio_cotizacion": False,
        "ia_cliente_respondio": True,
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


def test_da_igual_si_la_fecha_llega_como_texto_o_ya_convertida() -> None:
    # PostgREST la entrega como texto ISO; un cliente de Postgres, ya como datetime.
    texto = "2026-09-10T08:00:00-05:00"
    assert horas_desde(datetime.fromisoformat(texto), CORTE) == horas_desde(texto, CORTE)


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


# --------------------------------------------------------------------------------------
# frase_de_apertura
# --------------------------------------------------------------------------------------


def test_la_frase_reune_lo_que_el_asesor_necesita_para_marcar() -> None:
    frase = frase_de_apertura(fila(), CORTE)
    assert "Carlos" in frase
    assert "Bajaj Boxer CT 100" in frase
    assert "$2.000.000" in frase
    assert "crédito" in frase
    assert "Pidió cita" in frase
    assert "16 h sin contacto" in frase


def test_la_frase_es_la_misma_cada_vez() -> None:
    # Es una plantilla, no una llamada al modelo: mismo lead, misma frase, sin consumir cuota.
    assert frase_de_apertura(fila(), CORTE) == frase_de_apertura(fila(), CORTE)


def test_solo_se_usa_el_primer_nombre() -> None:
    assert frase_de_apertura(fila(nombre="Ana Lucía Restrepo"), CORTE).startswith("Ana ")


@pytest.mark.parametrize("vacio", [None, "", "   "])
def test_un_nombre_vacio_o_en_blanco_no_rompe_la_frase(vacio: object) -> None:
    # Hay registros con el nombre en blanco: `"   ".split()` es una lista vacía.
    assert frase_de_apertura(fila(nombre=vacio), CORTE).startswith("El cliente ")


def test_sin_conversacion_la_frase_lo_dice_y_pide_confirmar() -> None:
    # Prometer datos que no existen sería peor que no decir nada.
    frase = frase_de_apertura(fila(ia_conversaciones=0), CORTE)
    assert "no tiene conversación" in frase
    assert "Confirme modelo y forma de pago" in frase
    assert "$2.000.000" not in frase


def test_sin_conversacion_se_menciona_el_modelo_del_formulario() -> None:
    assert "Boxer CT 100" in frase_de_apertura(fila(ia_conversaciones=0), CORTE)


def test_una_objecion_se_advierte_antes_de_llamar() -> None:
    frase = frase_de_apertura(fila(ia_objecion="reporte_centrales"), CORTE)
    assert "Ojo" in frase and "reporte centrales" in frase


def test_se_avisa_cuando_el_cliente_dejo_de_responder() -> None:
    assert "No respondió al último mensaje" in frase_de_apertura(
        fila(ia_cliente_respondio=False), CORTE
    )


def test_un_lead_ya_gestionado_no_habla_de_horas_sin_contacto() -> None:
    # Las horas solo significan algo si nadie lo ha llamado todavía.
    frase = frase_de_apertura(fila(estado_gestion="Contactado"), CORTE)
    assert "sin contacto" not in frase


def test_el_pago_de_contado_se_dice_asi() -> None:
    assert "paga de contado" in frase_de_apertura(fila(ia_forma_pago="contado"), CORTE)


def test_la_cotizacion_se_menciona_cuando_no_hubo_cita() -> None:
    frase = frase_de_apertura(fila(ia_pidio_cita=False, ia_pidio_cotizacion=True), CORTE)
    assert "Pidió cotización" in frase


def test_una_conversacion_sin_datos_no_inventa_nada() -> None:
    frase = frase_de_apertura(
        fila(ia_modelo=None, ia_modelo_texto=None, ia_cuota_inicial_cop=None,
             ia_forma_pago="no_informa", ia_pidio_cita=False), CORTE
    )  # fmt: skip
    assert "escribió sin dar detalles" in frase
