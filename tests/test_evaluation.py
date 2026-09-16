"""Pruebas de la evaluación: comparación de campos, conjunto de referencia y cifras del informe."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from evaluation.eval_extraction import cargar_referencia, coincide, evaluar, tabla_markdown
from evaluation.validate_scoring import coma, razon_caliente_frio, tasa
from pipeline.extract.schema import Extraccion

# --------------------------------------------------------------------------------------
# coincide: cada campo se compara según su tipo
# --------------------------------------------------------------------------------------


def test_la_cuota_acepta_el_redondeo_del_cliente() -> None:
    # El cliente dice «unos 2 millones» y el modelo devuelve 2.050.000: es el mismo dato.
    assert coincide("cuota_inicial_cop", 2_000_000, 2_050_000)
    assert coincide("cuota_inicial_cop", 2_000_000, 1_950_000)


def test_una_cuota_muy_distinta_no_pasa() -> None:
    assert not coincide("cuota_inicial_cop", 2_000_000, 3_000_000)


def test_no_tener_cuota_y_tenerla_en_cero_son_cosas_distintas() -> None:
    assert coincide("cuota_inicial_cop", 0, 0)
    assert not coincide("cuota_inicial_cop", 0, 500_000)
    assert not coincide("cuota_inicial_cop", None, 0)
    assert coincide("cuota_inicial_cop", None, None)


def test_el_modelo_se_compara_sin_tildes_ni_mayusculas() -> None:
    assert coincide("modelo_texto", "Pulsár NS200", "pulsar ns200")


def test_el_resto_de_campos_se_compara_tal_cual() -> None:
    assert coincide("forma_pago", "credito", "credito")
    assert not coincide("forma_pago", "credito", "contado")


# --------------------------------------------------------------------------------------
# cargar_referencia: solo cuenta lo que revisó una persona
# --------------------------------------------------------------------------------------


def escribir(ruta: Path, registros: list[dict]) -> Path:
    ruta.write_text(json.dumps(registros), encoding="utf-8")
    return ruta


def test_solo_se_usan_los_registros_revisados(tmp_path: Path) -> None:
    ruta = escribir(
        tmp_path / "gold.json",
        [
            {"conversacion_id": "CV-1", "revisado": True},
            {"conversacion_id": "CV-2", "revisado": False},
            {"conversacion_id": "CV-3"},
        ],
    )
    assert [r["conversacion_id"] for r in cargar_referencia(ruta)] == ["CV-1"]


def test_sin_archivo_se_avisa_que_falta_revisarlo(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        cargar_referencia(tmp_path / "no_existe.json")


def test_un_borrador_sin_revisar_no_sirve_como_referencia(tmp_path: Path) -> None:
    # El borrador lo propone la IA: usarlo sería evaluar al modelo contra sí mismo.
    ruta = escribir(tmp_path / "gold.json", [{"conversacion_id": "CV-1", "revisado": False}])
    with pytest.raises(ValueError):
        cargar_referencia(ruta)


# --------------------------------------------------------------------------------------
# evaluar
# --------------------------------------------------------------------------------------


def extraccion(conversacion_id: str, **cambios) -> Extraccion:
    return Extraccion(conversacion_id=conversacion_id, **cambios)


def test_se_cuentan_los_aciertos_por_campo() -> None:
    referencia = [
        {"conversacion_id": "CV-1", "forma_pago": "contado"},
        {"conversacion_id": "CV-2", "forma_pago": "credito"},
    ]
    salida = {
        "CV-1": extraccion("CV-1", forma_pago="contado"),
        "CV-2": extraccion("CV-2", forma_pago="contado"),
    }
    assert evaluar(referencia, salida)["forma_pago"] == (1, 2)


def test_lo_que_el_extractor_no_resolvio_no_cuenta() -> None:
    # Si una conversación no se extrajo, no es un error de exactitud: no entra al denominador.
    referencia = [
        {"conversacion_id": "CV-1", "forma_pago": "contado"},
        {"conversacion_id": "CV-2", "forma_pago": "credito"},
    ]
    salida = {"CV-1": extraccion("CV-1", forma_pago="contado")}
    assert evaluar(referencia, salida)["forma_pago"] == (1, 1)


def test_un_campo_ausente_en_la_referencia_no_se_evalua() -> None:
    referencia = [{"conversacion_id": "CV-1"}]
    salida = {"CV-1": extraccion("CV-1")}
    assert evaluar(referencia, salida)["forma_pago"] == (0, 0)


def test_la_tabla_muestra_una_columna_por_extractor() -> None:
    referencia = [{"conversacion_id": "CV-1", "forma_pago": "contado"}]
    marcadores = {
        "gemini": evaluar(referencia, {"CV-1": extraccion("CV-1", forma_pago="contado")}),
        "reglas": evaluar(referencia, {"CV-1": extraccion("CV-1", forma_pago="credito")}),
    }
    tabla = tabla_markdown(marcadores)
    assert "| Campo | gemini | reglas |" in tabla
    assert "100,0 % (1/1)" in tabla and "0,0 % (0/1)" in tabla


# --------------------------------------------------------------------------------------
# Cifras del informe del puntaje
# --------------------------------------------------------------------------------------


def test_los_numeros_se_escriben_con_coma_decimal() -> None:
    assert coma(2.16) == "2,16"
    assert coma(0.6015, 3) == "0,602"


def test_la_coma_no_toca_el_resto_de_la_frase() -> None:
    # El reemplazo se hace sobre el número ya formateado, no sobre la frase que lo contiene.
    assert f"Resultado: {coma(2.16)} veces." == "Resultado: 2,16 veces."


def marco_cierres(temperaturas: list[str], cerrados: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"temperatura": temperaturas, "cerrado": cerrados})


def test_la_tasa_es_el_numero_de_cierres_sobre_el_grupo() -> None:
    n, valor = tasa(marco_cierres(["Caliente"] * 4, [1, 0, 0, 0]))
    assert (n, valor) == (4, 0.25)


def test_un_grupo_vacio_no_divide_por_cero() -> None:
    n, valor = tasa(marco_cierres([], []))
    assert n == 0 and pd.isna(valor)


def test_la_razon_compara_caliente_contra_frio() -> None:
    df = marco_cierres(["Caliente"] * 4 + ["Frío"] * 10, [1, 1, 0, 0] + [1] + [0] * 9)
    # Caliente 50 % contra Frío 10 %: cinco veces más.
    assert razon_caliente_frio(df) == pytest.approx(5.0)


def test_sin_frios_la_razon_no_es_un_numero() -> None:
    assert pd.isna(razon_caliente_frio(marco_cierres(["Caliente"], [1])))
