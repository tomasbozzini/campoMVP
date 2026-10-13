"""Saludos y repreguntas: respuestas cortas y fijas, escritas por el código."""

from typing import Annotated

from pydantic import BeforeValidator, Field

from app.ia.esquemas import Bandera, EsquemaAccion
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto

SALUDO = (
    "👋 *¡Hola!*\n\nContame qué hiciste y lo anoto, o preguntame por lo que tenés anotado.\n"
    "Mandá *ayuda* para ver ejemplos."
)
GRACIAS = "¡De nada! 👍"

# Preguntas fijas para cuando falta un dato. La IA elige cuáles faltan; el texto es del código.
PREGUNTAS = {
    "que_paso": "¿Qué querés que anote? Contame qué hiciste, por ejemplo: _vacuné 20 vacas en el lote 3_.",
    "establecimiento": "¿En qué establecimiento fue?",
    "cual_registro": (
        "¿Cuál de tus registros? Decime el tipo, la fecha, el lote o el campo. Con *¿qué tengo anotado?* ves la lista."
    ),
    "que_cambiar": "¿Qué querés cambiar de ese registro?",
    "cantidad": "¿Cuántos animales eran?",
    "producto": "¿Qué producto usaste?",
    "fecha": "¿Qué día fue?",
    "que_producto_precio": "¿De qué grano o categoría de hacienda querés el precio? Por ejemplo: _soja_, _novillo_.",
}


def repreguntar(*faltan: str) -> str:
    return "🤔 " + ("\n".join(dict.fromkeys(PREGUNTAS[f] for f in faltan)) or PREGUNTAS["que_paso"])


class Saludo(EsquemaAccion):
    agradece: Bandera = False


class Aclarar(EsquemaAccion):
    # Solo se usan las claves conocidas; cualquier otra cosa se ignora.
    falta: Annotated[
        list[str], BeforeValidator(lambda v: [f for f in v if f in PREGUNTAS] if isinstance(v, list) else [])
    ] = Field(default_factory=list)


def saludar(_ctx: Contexto, datos: Saludo) -> str:
    return GRACIAS if datos.agradece else SALUDO


def aclarar(_ctx: Contexto, datos: Aclarar) -> str:
    return repreguntar(*datos.falta)


ACCIONES = [
    Accion("saludo", Saludo, saludar, se_omite_si_hay_otras=True),
    Accion("aclarar", Aclarar, aclarar),
]
