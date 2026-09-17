"""Pruebas de la evaluación de robustez (TRD 8.5). No llaman a Gemini."""

from __future__ import annotations

import json
import re

from evaluation.eval_extraction import RUTA_GOLD
from evaluation.robustez import (
    RUTA_REFORMULACIONES,
    cargar_reformulaciones,
    reformular,
    reformular_conversaciones,
)
from pipeline.ingest import leer_conversaciones, leer_csv


def sust(original: str, reformulada: str) -> dict:
    return {"original": original, "reformulada": reformulada}


def conversacion(*mensajes: tuple[str, str]) -> dict:
    return {
        "conversacion_id": "CONV-1",
        "mensajes": [{"emisor": e, "hora": "10:00", "texto": t} for e, t in mensajes],
    }


# --------------------------------------------------------------------------------------
# reformular
# --------------------------------------------------------------------------------------


def test_se_reemplaza_sin_distinguir_mayusculas() -> None:
    texto, usadas = reformular("LISTO, ENVÍEMELA", [sust("Listo, envíemela", "mándemela")])
    assert texto == "mándemela"
    assert usadas == {"Listo, envíemela"}


def test_el_modelo_y_la_cifra_quedan_intactos() -> None:
    # Solo cambian las palabras alrededor: por eso las etiquetas de referencia siguen valiendo.
    texto, _ = reformular(
        "Financiada, tengo 2 palos para la inicial",
        [sust("Financiada, tengo", "a cuotas, y para arrancar le pongo")],
    )
    assert texto == "a cuotas, y para arrancar le pongo 2 palos para la inicial"


def test_la_frase_larga_se_aplica_antes_que_la_corta(tmp_path) -> None:
    # Si «Tengo» se aplicara primero, «Tengo como» ya no existiría cuando le tocara.
    ruta = tmp_path / "r.json"
    ruta.write_text(
        json.dumps(
            {
                "sustituciones": [
                    sust("Tengo", "cuento con"),
                    sust("Tengo como", "cuento con más o menos"),
                ]
            }
        ),
        encoding="utf-8",
    )
    sustituciones, _ = cargar_reformulaciones(ruta)
    assert (
        reformular("Tengo como 3 millones", sustituciones)[0] == "cuento con más o menos 3 millones"
    )


def test_un_reemplazo_con_barra_invertida_no_se_lee_como_grupo() -> None:
    assert reformular("hola", [sust("hola", r"qu\1é")])[0] == r"qu\1é"


def test_sin_revisar_se_informa_como_tal(tmp_path) -> None:
    ruta = tmp_path / "r.json"
    ruta.write_text(json.dumps({"sustituciones": []}), encoding="utf-8")
    assert cargar_reformulaciones(ruta)[1] is False


# --------------------------------------------------------------------------------------
# reformular_conversaciones
# --------------------------------------------------------------------------------------


def test_solo_se_reescriben_los_mensajes_del_cliente() -> None:
    original = conversacion(("cliente", "Listo, envíemela"), ("asesor", "Listo, envíemela"))
    [nueva], usadas, cambiados = reformular_conversaciones(
        [original], [sust("Listo, envíemela", "mándemela")]
    )
    assert [m["texto"] for m in nueva["mensajes"]] == ["mándemela", "Listo, envíemela"]
    assert cambiados == 1 and usadas == {"Listo, envíemela"}


def test_la_conversacion_original_no_se_modifica() -> None:
    original = conversacion(("cliente", "Ok gracias"))
    reformular_conversaciones([original], [sust("Ok gracias", "okis")])
    assert original["mensajes"][0]["texto"] == "Ok gracias"


# --------------------------------------------------------------------------------------
# El archivo versionado
# --------------------------------------------------------------------------------------


def test_ninguna_reformulacion_toca_cifras_ni_marcas() -> None:
    # Si una reformulación cambiara una cifra o un modelo, la etiqueta de referencia dejaría de
    # valer y la caída de exactitud ya no mediría fragilidad sino un cambio de respuesta.
    marcas = {m.lower() for m in leer_csv("catalogo_motos.csv")["marca"].str.strip()}
    sustituciones, _ = cargar_reformulaciones()
    for s in sustituciones:
        for lado in (s["original"], s["reformulada"]):
            assert not re.search(r"\d", lado), lado
            assert not any(marca in lado.lower() for marca in marcas), lado


def test_las_frases_originales_no_se_repiten() -> None:
    originales = [s["original"].lower() for s in cargar_reformulaciones()[0]]
    assert len(originales) == len(set(originales))


def test_cada_reformulacion_se_usa_en_el_conjunto_de_referencia() -> None:
    # Una frase mal copiada no se aplicaría y la prueba mediría menos de lo que declara.
    ids = {r["conversacion_id"] for r in json.loads(RUTA_GOLD.read_text(encoding="utf-8"))}
    conversaciones = [c for c in leer_conversaciones() if c["conversacion_id"] in ids]
    sustituciones, _ = cargar_reformulaciones(RUTA_REFORMULACIONES)
    _, usadas, _ = reformular_conversaciones(conversaciones, sustituciones)
    assert {s["original"] for s in sustituciones} == usadas
