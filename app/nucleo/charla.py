"""Contexto de la charla que ve la IA: solo de la misma persona y de los últimos minutos.

Sirve para entender respuestas cortas ("sí", "la de ayer", "La Pastora") después de una
pregunta del bot. Se guarda solo lo que se usa como contexto.
"""

from datetime import UTC, datetime, timedelta

from app.nucleo.cuaderno import Cuaderno

HISTORIAL_MENSAJES = 6
HISTORIAL_MINUTOS = 30
HISTORIAL_LARGO = 600  # caracteres por mensaje guardado


def historial(cuaderno: Cuaderno) -> list[tuple[str, str]]:
    desde = datetime.now(UTC) - timedelta(minutes=HISTORIAL_MINUTOS)
    return [(m.rol, m.texto) for m in cuaderno.charla(desde, HISTORIAL_MENSAJES)]


def guardar(cuaderno: Cuaderno, texto: str, respuesta: str) -> None:
    cuaderno.guardar_charla(
        [("usuario", texto[:HISTORIAL_LARGO]), ("bot", respuesta[:HISTORIAL_LARGO])],
        conservar=HISTORIAL_MENSAJES * 2,
    )
