"""Lo que el núcleo le pide a la IA: interpretar un mensaje y transcribir un audio."""

from collections.abc import Sequence
from datetime import date

from app.ia import prompt, proveedor


def interpretar(
    texto: str, hoy: date, historial: list[tuple[str, str]] | None = None, *, partes: Sequence[prompt.Parte]
) -> object:
    """El JSON que devuelve el modelo, sin validar, con el prompt armado con las partes de
    los módulos de la persona. La validación la hace el núcleo con los esquemas de cada
    acción: lo que no valida se descarta."""
    return proveedor.obtener().completar_json(prompt.sistema(hoy, partes), prompt.mensaje(texto, historial))


def transcribir(audio: bytes, nombre_archivo: str = "audio.ogg") -> str:
    return proveedor.obtener().transcribir(audio, nombre_archivo)
