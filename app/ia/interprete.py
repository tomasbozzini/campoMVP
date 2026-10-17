"""Lo que el núcleo le pide a la IA: interpretar un mensaje y transcribir un audio."""

import re
from collections.abc import Sequence
from datetime import date

from app.ia import prompt, proveedor
from app.infra.texto import sin_tildes


def interpretar(
    texto: str,
    hoy: date,
    historial: list[tuple[str, str]] | None = None,
    *,
    partes: Sequence[prompt.Parte],
    pregunta: str | None = None,
) -> object:
    """El JSON que devuelve el modelo, sin validar, con el prompt armado con las partes de
    los módulos de la persona. La validación la hace el núcleo con los esquemas de cada
    acción: lo que no valida se descarta. `pregunta`: la que el bot hizo y el mensaje no
    contestó con una respuesta fija, para que la IA reconozca si la cancela."""
    return proveedor.obtener().completar_json(prompt.sistema(hoy, partes), prompt.mensaje(texto, historial, pregunta))


def transcribir(audio: bytes, nombre_archivo: str = "audio.ogg", *, glosario: str, propios: Sequence[str] = ()) -> str:
    """El texto del audio. `glosario`: las palabras que tiene que escribir bien ("vaquillonas,
    novillos, ..., El Ombú"); vacío si no hay. `propios`: los nombres de los campos y lotes de
    la persona que van en el glosario.

    Devuelve "" si el audio no trae nada: con un audio en silencio o muy corto, Whisper a
    veces devuelve el glosario (o parte) en vez de una transcripción."""
    texto = proveedor.obtener().transcribir(audio, nombre_archivo, glosario)
    return "" if _solo_glosario(texto, glosario, propios) else texto


def _palabras(texto: str) -> set[str]:
    return set(re.findall(r"\w+", sin_tildes(texto.lower())))


def _solo_glosario(texto: str, glosario: str, propios: Sequence[str] = ()) -> bool:
    """Si la transcripción no tiene palabras, o todas son del glosario ("Vaquillonas,
    novillos."). Con una sola que no sea del glosario ("vacuné vaquillonas") es un mensaje, y
    también con un solo nombre propio: "El Ombú" es la respuesta a "¿en qué campo fue?"."""
    palabras = _palabras(texto)
    nombrados = [p for p in propios if _palabras(p) and _palabras(p) <= palabras]
    return palabras <= _palabras(glosario) and len(nombrados) != 1
