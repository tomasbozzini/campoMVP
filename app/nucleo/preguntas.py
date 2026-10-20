"""Las preguntas del bot que esperan una respuesta: qué se le cuenta a la IA y qué se contesta
si la persona cancela.

Las respuestas fijas (el número del rubro, la matrícula, *sí* / *no*) se resuelven sin IA. Si
el mensaje no es una de esas, la pregunta se descarta y el mensaje va a la IA con la pregunta
como contexto: si la cancela con cualquier frase ("no, no, dejá, no quiero cambiar nada"),
devuelve "cancelar"; si no, el mensaje sigue como un pedido normal (paso 8.5 del plan).

El texto para la IA es fijo, del código: nunca lleva lo que escribió la persona.
"""

from dataclasses import dataclass

RUBRO, MATRICULA, BORRAR, CORREGIR, CAMPO, FECHA = "rubro", "matricula", "borrar", "corregir", "campo", "fecha"

SIN_CAMBIOS = "👌 Listo, no cambié nada."


@dataclass(frozen=True)
class Pregunta:
    para_la_ia: str  # qué preguntó el sistema, en pocas palabras
    al_cancelar: str  # la respuesta si la persona la cancela


PREGUNTAS = {
    RUBRO: Pregunta("¿A qué te dedicás? (para cambiar su rubro: veterinario, agrónomo o productor)", SIN_CAMBIOS),
    MATRICULA: Pregunta("¿Cuál es tu matrícula? (para cargar o cambiar su matrícula profesional)", SIN_CAMBIOS),
    BORRAR: Pregunta("¿Confirmás que borre lo que te mostré? (sí o no)", "👌 Listo, no borré nada."),
    CORREGIR: Pregunta("¿Confirmás que corrija los pendientes que te mostré? (sí o no)", SIN_CAMBIOS),
    CAMPO: Pregunta(
        "¿Es el mismo campo que ya tenés cargado? (sí: es ese; no: es otro campo nuevo)", "👌 Listo, no anoté nada."
    ),
    FECHA: Pregunta(
        "¿Para cuándo? (el día de la semana y el número que dijo no coinciden; le mostré dos fechas: 1 o 2)",
        "👌 Listo, no anoté nada.",
    ),
}


def para_la_ia(clave: str | None) -> str | None:
    return PREGUNTAS[clave].para_la_ia if clave in PREGUNTAS else None


def al_cancelar(clave: str | None) -> str:
    return PREGUNTAS[clave].al_cancelar if clave in PREGUNTAS else "👌 Listo."
