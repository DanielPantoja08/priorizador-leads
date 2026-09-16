"""Pruebas del extractor por reglas (TRD 14): jerga de montos, '0 millones', cambio de modelo y silencio."""

from __future__ import annotations

import pytest

from pipeline.extract.rules import ExtractorReglas, monto_en

MARCAS = ["AKT", "Bajaj", "Honda", "Suzuki", "TVS", "Yamaha"]


SALUDO = "Buenas, estoy interesado"


def conversacion(*textos_cliente: str, asesor: str = "Con mucho gusto le colaboro") -> dict:
    """Arma una conversación intercalando la respuesta del asesor después de cada mensaje.

    Antepone el saludo del cliente: una conversación de un solo mensaje suyo significa que
    nunca volvió a escribir, y eso es justo lo que prueba `test_conversacion_sin_respuesta`.
    """
    mensajes = []
    for texto in (SALUDO, *textos_cliente):
        mensajes.append({"emisor": "cliente", "hora": "10:00", "texto": texto})
        mensajes.append({"emisor": "asesor", "hora": "10:01", "texto": asesor})
    return {"conversacion_id": "CONV-TEST", "lead_id": "LEAD-1", "mensajes": mensajes}


def extraer(*textos: str):
    return ExtractorReglas(MARCAS).extraer([conversacion(*textos)])[0]


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Tengo como 2 palos", 2_000_000),
        ("Tengo como 2 millonzitos", 2_000_000),
        ("Tengo 7,2 millones", 7_200_000),
        ("Tengo 1500mil", 1_500_000),
        ("Tengo 1000mil", 1_000_000),
        ("Tengo 0,5 millones", 500_000),
        ("Tengo 1 millones", 1_000_000),
        # Cifra escrita completa, como aparece en los datos.
        ("Esa sí me sirve. Tengo $1.500.000 de inicial", 1_500_000),
        ("Financiada. Tengo como $500.000, ¿alcanza para la inicial?", 500_000),
        ("De contado, ya tengo la plata lista, $10.490.000", 10_490_000),
        ("No hablo de plata", None),
    ],
)
def test_montos_en_jerga(texto: str, esperado: int | None) -> None:
    assert monto_en(texto) == esperado


def test_cero_millones_es_sin_inicial() -> None:
    e = extraer("Financiada. Tengo como 0 millones, ¿alcanza para la inicial?")
    assert e.cuota_inicial_cop == 0
    assert e.menciona_cuota == "NO"
    assert e.objecion == "sin_inicial"
    assert e.forma_pago == "credito"


def test_no_tengo_inicial() -> None:
    e = extraer("No tengo con qué dar la inicial ahora")
    assert (e.cuota_inicial_cop, e.menciona_cuota) == (0, "NO")


def test_sin_mencion_de_cuota() -> None:
    e = extraer("Hola, me interesa la Honda CB 190R")
    assert e.cuota_inicial_cop is None
    assert e.menciona_cuota == "NO_INFORMA"


def test_cambio_de_modelo_gana_el_ultimo() -> None:
    e = extraer(
        "Hola buenas, me interesa la Bajaj Pulsar NS 160",
        "¿Y no tienen algo más económico? tipo la Honda CB 190R",
    )
    assert e.modelo_texto == "Honda CB 190R"


def test_modelo_no_arrastra_el_resto_de_la_frase() -> None:
    e = extraer("Buenos días, quiero información de la Suzuki GN 125 y cuánto vale")
    assert e.modelo_texto == "Suzuki GN 125"


def test_conversacion_sin_respuesta_del_cliente() -> None:
    conv = {
        "conversacion_id": "CONV-SILENCIO",
        "lead_id": "LEAD-2",
        "mensajes": [
            {
                "emisor": "cliente",
                "hora": "09:00",
                "texto": "Buenas, vi el anuncio de la AKT NKD 125",
            },
            {"emisor": "asesor", "hora": "09:05", "texto": "Con mucho gusto, está en $6.000.000"},
            {"emisor": "asesor", "hora": "11:00", "texto": "¿Sigue interesado? quedo atento"},
        ],
    }
    e = ExtractorReglas(MARCAS).extraer([conv])[0]
    assert e.cliente_respondio is False
    assert e.intencion == "baja"
    assert e.modelo_texto == "AKT NKD 125"


def test_pide_cita_es_intencion_alta() -> None:
    e = extraer("¿Mañana los visito?")
    assert e.pidio_cita is True
    assert e.intencion == "alta"


def test_separar_la_moto_es_cita() -> None:
    assert extraer("Listo, sepáremela").pidio_cita is True


def test_consultar_en_la_casa_no_es_cita() -> None:
    e = extraer("Voy a consultar en la casa y le digo")
    assert e.pidio_cita is False
    assert e.objecion == "consultar_familia"


def test_acepta_cotizacion() -> None:
    assert extraer("Listo, envíemela").pidio_cotizacion is True


def test_solo_mirando_es_baja() -> None:
    e = extraer("Solo estaba mirando precios")
    assert e.intencion == "baja"
    assert e.objecion == "solo_averiguando"


@pytest.mark.parametrize(
    ("texto", "objecion"),
    [
        ("Estoy en centrales", "reporte_centrales"),
        ("Esa tasa está muy alta", "tasa_cuota"),
        ("¿No tienen usadas?", "prefiere_usada"),
        ("¿Y cuánto se demora la entrega? necesito la moto ya", "tiempo_entrega"),
        ("Estoy es comparando por ahora", "comparando"),
        ("¿Y no tienen algo más económico?", "precio"),
        ("No, eso se me sale del presupuesto", "precio"),
        ("Muy costosa la verdad", "precio"),
        ("Está por encima de lo que tengo", "precio"),
        ("Es que la inicial está muy alta", "precio"),
        ("Dale pues", "ninguna"),
    ],
)
def test_objeciones(texto: str, objecion: str) -> None:
    assert extraer(texto).objecion == objecion


def test_hablar_de_inicial_implica_credito() -> None:
    # El cliente nunca dice "financiada", pero hablar de inicial es estar financiando.
    e = extraer("Esa sí me sirve. Tengo 2 millones de inicial")
    assert e.forma_pago == "credito"
    assert e.cuota_inicial_cop == 2_000_000


def test_no_tener_inicial_tambien_es_credito() -> None:
    assert extraer("No tengo inicial").forma_pago == "credito"


def test_contado_gana_sobre_credito() -> None:
    e = extraer("De contado, ya tengo la plata lista, 7,2 millones")
    assert e.forma_pago == "contado"
    assert e.cuota_inicial_cop == 7_200_000


def test_evidencia_cita_el_texto_del_cliente() -> None:
    e = extraer("Financiada, tengo 2,0 millones para la inicial")
    assert "2,0 millones" in e.evidencia["cuota_inicial_cop"]
