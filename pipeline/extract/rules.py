"""Extractor por reglas (TRD 8.3): expresiones regulares sobre los mensajes del cliente.

Cumple dos funciones: respaldo cuando el LLM falla, y línea base de la evaluación.
Solo lee los mensajes del **cliente**: lo que dice el asesor no es una señal del cliente.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pipeline.extract.base import VERSION_REGLAS, cliente_respondio, mensajes_de
from pipeline.extract.schema import Extraccion, FormaPago, Intencion, Objecion

# ---------------------------------------------------------------------------
# Montos y jerga (TRD 8.2: "palos" y "millonzitos" son millones; "1500mil" son 1.500.000)
# ---------------------------------------------------------------------------
UNIDADES = {
    "millon": 1_000_000,
    "millón": 1_000_000,
    "millones": 1_000_000,
    "palo": 1_000_000,
    "palos": 1_000_000,
    "millonzito": 1_000_000,
    "millonzitos": 1_000_000,
    "mil": 1_000,
}
# El número admite coma o punto decimal y puede ir pegado a la unidad ("1000mil").
_MONTO = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(millones|millón|millon|millonzitos|millonzito|palos|palo|mil)\b", re.I
)

# Montos escritos en pesos con separador de miles: "$1.500.000". En los datos siempre llevan
# el signo, así que exigirlo evita confundir la cifra con un cilindraje o un año.
_PESOS = re.compile(r"\$\s?(\d{1,3}(?:\.\d{3})+)")

# Dice explícitamente que no tiene con qué dar la inicial.
_SIN_INICIAL = re.compile(
    r"no tengo (con qu[eé] dar la |nada para la )?(la )?inicial|sin inicial|no tengo nada", re.I
)

# ---------------------------------------------------------------------------
# Forma de pago, cita y cotización
# ---------------------------------------------------------------------------
_CONTADO = re.compile(r"\b(de |al )?contado\b|la plata lista", re.I)
# Hablar de cuota inicial es financiar, aunque el cliente no diga "financiada" (criterio del prompt v2).
_CREDITO = re.compile(r"financiad|financiar|\bcr[eé]dito\b|\bcuotas\b|\binicial\b", re.I)

# "voy" solo cuenta con un complemento de desplazamiento: "voy a consultar" no es una visita.
_CITA = re.compile(
    r"\bvisit(o|ar|arlos|arlo)\b|\bsep[aá]r(emela|ela|emelo|elo|ar|o)\b"
    r"|\bvoy (en camino|saliendo|esta tarde|para all[aá]|ya)\b|\bya voy\b"
    r"|\bpas(o|ar|ar[ií]a)\b[^.?!]{0,25}\b(sede|local|vitrina|por all[aá])\b"
    r"|\bpuedo pasar\b|\blos visito\b",
    re.I,
)
# El asesor ofrece "¿Le mando la cotización formal?"; estas son las formas de aceptar.
_COTIZACION = re.compile(
    r"env[ií]e(mela|la|melo)?|m[aá]nd(emela|ela|emelo|elo|e|a)\b|cotiza(ci[oó]n|r|me)?", re.I
)

# ---------------------------------------------------------------------------
# Intención (TRD 8.1)
# ---------------------------------------------------------------------------
_URGENCIA = re.compile(r"la necesito esta semana|necesito la moto ya|urgente|para ya", re.I)
_DESINTERES = re.compile(
    r"solo estaba mirando|solo mirando|por curiosidad|solo (estoy )?averiguando|no me interesa|ya no",
    re.I,
)

# ---------------------------------------------------------------------------
# Objeciones, en orden de prioridad: la primera que coincide es la que queda.
# ---------------------------------------------------------------------------
OBJECIONES: tuple[tuple[Objecion, re.Pattern[str]], ...] = (
    ("reporte_centrales", re.compile(r"centrales|datacr[eé]dito|reportad|reporte viejo", re.I)),
    ("sin_inicial", _SIN_INICIAL),
    (
        "tasa_cuota",
        re.compile(
            r"\btasa\b|inter[eé]s (est[aá] )?(muy )?(caro|alto)|cu[aá]nto queda la cuota|cuota mensual",
            re.I,
        ),
    ),
    ("prefiere_usada", re.compile(r"\busada?s?\b", re.I)),
    (
        "tiempo_entrega",
        re.compile(
            r"demora la entrega|cu[aá]ndo.{0,15}entregan|entrega inmediata|necesito la moto ya",
            re.I,
        ),
    ),
    (
        "consultar_familia",
        re.compile(
            r"lo hablo con mi|hablar con mi|consultar (en la casa|con)|con mi (esposa|esposo|se[ñn]ora|marido|familia)|en la casa y le digo",
            re.I,
        ),
    ),
    (
        "comparando",
        re.compile(
            r"comparando|otra marca|me est[aá]n ofreciendo otra|mirando tambi[eé]n|cotizando en otra",
            re.I,
        ),
    ),
    (
        "precio",
        re.compile(
            r"m[aá]s econ[oó]mic|muy caro|est[aá] caro|m[aá]s barat|no me alcanza"
            r"|sale del presupuesto|fuera de presupuesto|muy costosa?|inicial est[aá] muy alta"
            r"|por encima de lo que tengo",
            re.I,
        ),
    ),
    ("solo_averiguando", _DESINTERES),
)


def _a_pesos(cantidad: str, unidad: str) -> int:
    """'2,0' + 'millones' -> 2000000. '1500' + 'mil' -> 1500000."""
    return round(float(cantidad.replace(",", ".")) * UNIDADES[unidad.lower()])


def monto_en(texto: str) -> int | None:
    """Último monto del texto en pesos, o None si no menciona ninguno.

    Convive la jerga ("2 palos") con la cifra escrita completa ("$1.500.000"); gana la que
    aparezca más adelante en la frase, que es el dato con el que el cliente se queda.
    """
    candidatos = [(m.end(), _a_pesos(m.group(1), m.group(2))) for m in _MONTO.finditer(texto)]
    candidatos += [(m.end(), int(m.group(1).replace(".", ""))) for m in _PESOS.finditer(texto)]
    return max(candidatos)[1] if candidatos else None


class ExtractorReglas:
    """Extrae las señales con expresiones regulares. No llama a ningún servicio externo."""

    nombre = "reglas"
    version = VERSION_REGLAS

    def __init__(self, marcas: Sequence[str]) -> None:
        """`marcas` son las del catálogo: delimitan dónde empieza la mención de un modelo."""
        patron = "|".join(sorted((re.escape(m) for m in marcas), key=len, reverse=True))
        self._marca = re.compile(rf"\b({patron})\b([\w\s.\-]*)", re.I)

    # -- modelo ------------------------------------------------------------
    def _modelo(self, textos: list[str]) -> str | None:
        """El ÚLTIMO modelo que menciona el cliente (TRD 8.2)."""
        ultimo = None
        for texto in textos:
            for coincidencia in self._marca.finditer(texto):
                ultimo = _recortar_modelo(coincidencia.group(1), coincidencia.group(2))
        return ultimo

    # -- cuota -------------------------------------------------------------
    def _cuota(self, textos: list[str]) -> tuple[int | None, str, str | None]:
        """Devuelve (cuota, menciona_cuota, evidencia). El monto de contado cuenta como lo que puede poner."""
        for texto in reversed(textos):  # el dato más reciente manda
            monto = monto_en(texto)
            if monto is not None:
                return monto, ("SI" if monto > 0 else "NO"), texto
            if _SIN_INICIAL.search(texto):
                return 0, "NO", texto
        return None, "NO_INFORMA", None

    # -- forma de pago -----------------------------------------------------
    def _forma_pago(self, textos: list[str]) -> tuple[FormaPago, str | None]:
        for texto in textos:
            if _CONTADO.search(texto):
                return "contado", texto
            if _CREDITO.search(texto):
                return "credito", texto
        return "no_informa", None

    def extraer(self, conversaciones: list[dict]) -> list[Extraccion]:
        """Una extracción por conversación, en el mismo orden."""
        return [self._una(c) for c in conversaciones]

    def _una(self, conversacion: dict) -> Extraccion:
        textos = mensajes_de(conversacion)
        respondio = cliente_respondio(conversacion)
        evidencia: dict[str, str] = {}

        modelo = self._modelo(textos)
        cuota, menciona, ev_cuota = self._cuota(textos)
        forma_pago, ev_pago = self._forma_pago(textos)
        cita = _primera(textos, _CITA)
        cotizacion = _primera(textos, _COTIZACION)
        objecion, ev_objecion = _objecion(textos, cuota)
        intencion = _intencion(
            textos, respondio, bool(cita), bool(cotizacion), menciona, forma_pago
        )

        for campo, valor in (
            ("cuota_inicial_cop", ev_cuota),
            ("forma_pago", ev_pago),
            ("pidio_cita", cita),
            ("pidio_cotizacion", cotizacion),
            ("objecion", ev_objecion),
        ):
            if valor:
                evidencia[campo] = valor[:160]

        return Extraccion(
            conversacion_id=conversacion["conversacion_id"],
            modelo_texto=modelo,
            cuota_inicial_cop=cuota,
            menciona_cuota=menciona,
            forma_pago=forma_pago,
            intencion=intencion,
            objecion=objecion,
            pidio_cita=bool(cita),
            pidio_cotizacion=bool(cotizacion),
            cliente_respondio=respondio,
            evidencia=evidencia,
        )


def _recortar_modelo(marca: str, resto: str) -> str:
    """Deja la marca y hasta tres partes del nombre; corta al llegar a una palabra que no es del modelo."""
    partes = [marca]
    for palabra in resto.split():
        # Las partes del nombre son cilindrajes o siglas: dígitos, o palabras cortas con mayúscula.
        if len(partes) > 3 or not (any(c.isdigit() for c in palabra) or palabra[:1].isupper()):
            break
        partes.append(palabra.strip(".,;:¿?¡!"))
    return " ".join(p for p in partes if p)


def _primera(textos: list[str], patron: re.Pattern[str]) -> str | None:
    """Primer texto que coincide con el patrón; sirve como evidencia del campo."""
    return next((t for t in textos if patron.search(t)), None)


def _objecion(textos: list[str], cuota: int | None) -> tuple[Objecion, str | None]:
    """La objeción de mayor prioridad presente en la conversación.

    Decir "tengo 0 millones" es la misma objeción que "no tengo inicial", aunque no use esas palabras.
    """
    for nombre, patron in OBJECIONES:
        if texto := _primera(textos, patron):
            return nombre, texto
        if nombre == "sin_inicial" and cuota == 0:
            return "sin_inicial", _primera(textos, _MONTO)
    return "ninguna", None


def _intencion(
    textos: list[str],
    respondio: bool,
    cita: bool,
    cotizacion: bool,
    menciona_cuota: str,
    forma_pago: FormaPago,
) -> Intencion:
    """Criterios de TRD 8.1: alta si pide visita o urgencia; baja si no responde o solo mira."""
    if not respondio:
        return "baja"
    if cita or any(_URGENCIA.search(t) for t in textos):
        return "alta"
    if any(_DESINTERES.search(t) for t in textos):
        return "baja"
    # Se despidió sin dejar ninguna señal de avance.
    if not (cotizacion or menciona_cuota == "SI" or forma_pago != "no_informa"):
        return "baja"
    return "media"
