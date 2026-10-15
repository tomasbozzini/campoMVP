"""Interfaz con el modelo de lenguaje. El resto del código no sabe qué proveedor se usa.

Para cambiar de proveedor alcanza con escribir otra clase que cumpla `ProveedorIA` y
devolverla en `obtener()`.
"""

from typing import Protocol


class ErrorIA(RuntimeError):
    """Falló el pedido a la IA. El mensaje dice solo el tipo de error y el código de estado:
    las respuestas de error del proveedor pueden repetir el texto de la persona."""


class ProveedorIA(Protocol):
    def completar_json(self, sistema: str, mensaje: str) -> object:
        """Respuesta del modelo como JSON ya leído (sin validar: lo valida quien la usa)."""
        ...

    def transcribir(self, audio: bytes, nombre_archivo: str, glosario: str) -> str:
        """El texto del audio. `glosario`: palabras que tiene que escribir bien (puede ser vacío)."""
        ...


_proveedor: ProveedorIA | None = None


def obtener() -> ProveedorIA:
    global _proveedor
    if _proveedor is None:
        from app.ia.proveedor_groq import ProveedorGroq
        from app.infra.config import config

        _proveedor = ProveedorGroq(config.groq_api_key, config.groq_modelo, config.groq_modelo_audio)
    return _proveedor


def usar(proveedor: ProveedorIA | None) -> None:
    """Reemplaza el proveedor (por ejemplo, uno falso en los tests). None vuelve al de la configuración."""
    global _proveedor
    _proveedor = proveedor
