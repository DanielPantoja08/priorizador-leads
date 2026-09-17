"""Pruebas de la validación posterior del esquema de extracción (TRD 8.1)."""

from __future__ import annotations

import pytest

from pipeline.extract.schema import Extraccion, ExtraccionLLM, como_desconocidos, validar

PRECIO = 7_190_000


def con_cuota(valor: int | None, menciona: str = "SI") -> Extraccion:
    return Extraccion(conversacion_id="CONV-1", cuota_inicial_cop=valor, menciona_cuota=menciona)


def test_cuota_dentro_del_precio_no_se_toca() -> None:
    validada, correcciones = validar(con_cuota(2_000_000), PRECIO)
    assert validada.cuota_inicial_cop == 2_000_000
    assert correcciones == []


def test_redondeo_del_cliente_se_recorta_al_precio() -> None:
    # "7,2 millones" para una moto de 7.190.000: son 10.000 pesos, el cliente redondeó.
    validada, correcciones = validar(con_cuota(7_200_000), PRECIO)
    assert validada.cuota_inicial_cop == PRECIO
    assert correcciones == ["cuota_redondeada_al_precio"]
    assert validada.menciona_cuota == "SI"


def test_cifra_muy_por_encima_del_precio_se_anula() -> None:
    validada, correcciones = validar(con_cuota(20_000_000), PRECIO)
    assert validada.cuota_inicial_cop is None
    assert correcciones == ["cuota_mayor_que_precio"]


def test_limite_exacto_de_la_tolerancia_se_recorta() -> None:
    validada, correcciones = validar(con_cuota(int(PRECIO * 1.05)), PRECIO)
    assert validada.cuota_inicial_cop == PRECIO
    assert correcciones == ["cuota_redondeada_al_precio"]


def test_cuota_negativa_se_anula() -> None:
    validada, correcciones = validar(con_cuota(-1000), PRECIO)
    assert validada.cuota_inicial_cop is None
    assert correcciones == ["cuota_negativa"]


def test_sin_precio_de_referencia_no_se_recorta() -> None:
    # Si el modelo no se pudo resolver contra el catálogo, no hay contra qué comparar.
    validada, correcciones = validar(con_cuota(50_000_000), None)
    assert validada.cuota_inicial_cop == 50_000_000
    assert correcciones == []


@pytest.mark.parametrize(
    ("cuota", "declarado", "esperado"),
    [(2_000_000, "NO", "SI"), (0, "SI", "NO"), (0, "NO_INFORMA", "NO")],
)
def test_coherencia_entre_cuota_y_mencion(cuota: int, declarado: str, esperado: str) -> None:
    validada, correcciones = validar(con_cuota(cuota, declarado), PRECIO)
    assert validada.menciona_cuota == esperado
    assert "menciona_cuota_incoherente" in correcciones


def test_sin_cuota_no_se_toca_la_mencion() -> None:
    validada, correcciones = validar(con_cuota(None, "NO_INFORMA"), PRECIO)
    assert validada.menciona_cuota == "NO_INFORMA"
    assert correcciones == []


def test_la_evidencia_del_llm_se_convierte_en_diccionario() -> None:
    crudo = ExtraccionLLM(
        conversacion_id="CONV-1",
        evidencia=[
            {"campo": "pidio_cita", "fragmento": "¿Mañana los visito?"},
            {"campo": "forma_pago", "fragmento": "De contado"},
        ],
    )
    extraccion = crudo.a_extraccion()
    assert extraccion.evidencia == {
        "pidio_cita": "¿Mañana los visito?",
        "forma_pago": "De contado",
    }


# --- Campos sin respaldo en el chat ------------------------------------------------------------


def test_un_campo_sin_respaldo_vuelve_a_su_valor_desconocido() -> None:
    e = Extraccion(conversacion_id="C1", pidio_cita=True, intencion="baja", objecion="precio")
    limpia = como_desconocidos(e, ["pidio_cita", "intencion"])
    assert (limpia.pidio_cita, limpia.intencion) == (False, "media")
    assert limpia.objecion == "precio"  # lo que sí tiene respaldo no se toca


def test_la_cuota_y_su_mencion_caen_juntas() -> None:
    e = Extraccion(conversacion_id="C1", cuota_inicial_cop=2_000_000, menciona_cuota="SI")
    limpia = como_desconocidos(e, ["menciona_cuota"])
    assert (limpia.cuota_inicial_cop, limpia.menciona_cuota) == (None, "NO_INFORMA")


def test_un_no_respondio_sin_respaldo_deja_de_restar() -> None:
    limpia = como_desconocidos(
        Extraccion(conversacion_id="C1", cliente_respondio=False), ["cliente_respondio"]
    )
    assert limpia.cliente_respondio is True


def test_la_evidencia_original_se_conserva() -> None:
    e = Extraccion(conversacion_id="C1", pidio_cita=True, evidencia={"pidio_cita": "inventado"})
    assert como_desconocidos(e, ["pidio_cita"]).evidencia == {"pidio_cita": "inventado"}
