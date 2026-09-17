"""Esquema de salida de la extracción y sus validaciones (TRD 8.1).

`Extraccion` es el contrato que usan los dos extractores, la base de datos y la evaluación.
`ExtraccionLLM` es la misma información con la evidencia como lista de pares: es la forma que se
le pide a Gemini, porque un objeto de claves libres no se puede describir en un esquema JSON.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Enumeraciones del TRD 8.1. Se declaran aparte para reutilizarlas en las pruebas y la evaluación.
MencionaCuota = Literal["SI", "NO", "NO_INFORMA"]
FormaPago = Literal["contado", "credito", "no_informa"]
Intencion = Literal["alta", "media", "baja"]
Objecion = Literal[
    "precio",
    "tasa_cuota",
    "sin_inicial",
    "reporte_centrales",
    "comparando",
    "consultar_familia",
    "prefiere_usada",
    "tiempo_entrega",
    "solo_averiguando",
    "ninguna",
]

# El cliente redondea la cifra al decirla: "7,2 millones" por una moto de 7.190.000. Por debajo de
# este margen se toma como redondeo y se recorta al precio; por encima, la cifra se descarta.
TOLERANCIA_PRECIO = 0.05

# Campos que se comparan contra el conjunto de referencia (TRD 8.5).
CAMPOS_EVALUADOS = (
    "modelo_texto",
    "cuota_inicial_cop",
    "menciona_cuota",
    "forma_pago",
    "intencion",
    "objecion",
    "pidio_cita",
    "pidio_cotizacion",
    "cliente_respondio",
)


class Extraccion(BaseModel):
    """Señales que el cliente dejó en una conversación."""

    model_config = ConfigDict(extra="ignore")

    conversacion_id: str
    modelo_texto: str | None = None  # el ÚLTIMO modelo de interés que menciona el cliente
    cuota_inicial_cop: int | None = None  # en pesos; 0 si dice que no tiene
    menciona_cuota: MencionaCuota = "NO_INFORMA"
    forma_pago: FormaPago = "no_informa"
    intencion: Intencion = "media"
    objecion: Objecion = "ninguna"
    pidio_cita: bool = False  # quiere visitar la sede o separar la moto
    pidio_cotizacion: bool = False
    cliente_respondio: bool = True  # False si solo hay mensajes del asesor tras el saludo
    evidencia: dict[str, str] = Field(default_factory=dict)  # campo -> fragmento textual breve


class ParEvidencia(BaseModel):
    """Un fragmento que justifica un campo. Forma que entiende el esquema JSON del LLM."""

    campo: str
    fragmento: str


class ExtraccionLLM(BaseModel):
    """Lo que se le pide a Gemini. Igual a `Extraccion`, con la evidencia como lista."""

    model_config = ConfigDict(extra="ignore")

    conversacion_id: str
    modelo_texto: str | None = None
    cuota_inicial_cop: int | None = None
    menciona_cuota: MencionaCuota = "NO_INFORMA"
    forma_pago: FormaPago = "no_informa"
    intencion: Intencion = "media"
    objecion: Objecion = "ninguna"
    pidio_cita: bool = False
    pidio_cotizacion: bool = False
    cliente_respondio: bool = True
    evidencia: list[ParEvidencia] = Field(default_factory=list)

    def a_extraccion(self) -> Extraccion:
        """Convierte la evidencia a diccionario; si un campo se repite, queda el último fragmento."""
        datos = self.model_dump()
        datos["evidencia"] = {p["campo"]: p["fragmento"] for p in datos["evidencia"]}
        return Extraccion(**datos)


def validar(
    extraccion: Extraccion, precio_lista: int | None = None
) -> tuple[Extraccion, list[str]]:
    """Aplica las reglas posteriores de TRD 8.1 y devuelve la extracción corregida y qué se corrigió.

    - La cuota debe estar entre 0 y el precio de lista del modelo. Si lo supera por menos de
      `TOLERANCIA_PRECIO` se entiende como redondeo del cliente y se recorta al precio; si lo
      supera por más, la cifra no es creíble y pasa a nulo. Un valor negativo también pasa a nulo.
    - `cuota > 0` implica `menciona_cuota = SI` y `cuota = 0` implica `NO`.
    """
    correcciones: list[str] = []
    datos = extraccion.model_dump()
    cuota = datos["cuota_inicial_cop"]

    if cuota is not None and cuota < 0:
        correcciones.append("cuota_negativa")
        cuota = None
    elif cuota is not None and precio_lista is not None and cuota > precio_lista:
        if cuota <= precio_lista * (1 + TOLERANCIA_PRECIO):
            correcciones.append("cuota_redondeada_al_precio")
            cuota = precio_lista
        else:
            correcciones.append("cuota_mayor_que_precio")
            cuota = None
    datos["cuota_inicial_cop"] = cuota

    if cuota is not None:
        esperado = "SI" if cuota > 0 else "NO"
        if datos["menciona_cuota"] != esperado:
            correcciones.append("menciona_cuota_incoherente")
            datos["menciona_cuota"] = esperado

    return Extraccion(**datos), correcciones


# La cuota y su mención son una sola afirmación: si una no tiene respaldo, tampoco la otra.
CAMPOS_DE_CUOTA = ("cuota_inicial_cop", "menciona_cuota")


def como_desconocidos(extraccion: Extraccion, campos: list[str]) -> Extraccion:
    """La extracción con esos campos devueltos a su valor por defecto, que es el «no se sabe».

    Se usa con los campos cuya evidencia no aparece en la conversación: un valor sin respaldo no
    debe sumar ni restar en el puntaje. Los valores por defecto de `Extraccion` son justamente los
    neutros (`NO_INFORMA`, `no_informa`, intención media, sin objeción, respondió).
    """
    datos = extraccion.model_dump()
    for campo in campos:
        for afectado in CAMPOS_DE_CUOTA if campo in CAMPOS_DE_CUOTA else (campo,):
            if afectado in Extraccion.model_fields and afectado != "conversacion_id":
                datos[afectado] = Extraccion.model_fields[afectado].get_default(
                    call_default_factory=True
                )
    return Extraccion(**datos)
