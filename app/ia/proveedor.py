"""Interfaz con el modelo de lenguaje. El resto del código no sabe qué proveedor se usa.

Con OPENROUTER_API_KEY, los mensajes los interpreta OpenRouter y Groq queda de respaldo (y
transcribe los audios); sin la clave, todo va por Groq. Para cambiar de proveedor alcanza
con escribir otra clase que cumpla `ProveedorIA` (o `ProveedorTexto`, si solo interpreta) y
armarla en `obtener()`.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)


class ErrorIA(RuntimeError):
    """Falló el pedido a la IA. El mensaje dice solo el tipo de error y el código de estado:
    las respuestas de error del proveedor pueden repetir el texto de la persona."""


class IASaturada(ErrorIA):
    """La IA no atiende ahora: límite de pedidos, sin saldo, sin respuesta o sin servidores
    disponibles. No es culpa del mensaje: en un rato puede andar."""


@dataclass(frozen=True)
class Uso:
    """Lo que gastó un pedido a la IA. Sin nada del mensaje: se puede loguear."""

    proveedor: str  # "openrouter", "groq"
    servidor: str | None  # quién corrió el modelo, si el proveedor lo dice (OpenRouter elige uno)
    tokens_entrada: int
    tokens_salida: int  # incluye los de razonamiento
    tokens_razonamiento: int
    costo_usd: float | None  # lo que informa el proveedor; None si no lo informa
    segundos: float


_medicion: ContextVar[list[Uso] | None] = ContextVar("medicion", default=None)


def anotar_uso(uso: Uso) -> None:
    """Lo llaman los proveedores después de cada pedido: queda en el log (así se ve quién
    respondió) y en la medición en curso, si hay una."""
    costo = f", USD {uso.costo_usd:.6f}" if uso.costo_usd is not None else ""
    servidor = f" ({uso.servidor})" if uso.servidor else ""
    log.info(
        "IA %s%s: %d + %d tokens%s, %.1f s",
        uso.proveedor,
        servidor,
        uso.tokens_entrada,
        uso.tokens_salida,
        costo,
        uso.segundos,
    )
    if (usos := _medicion.get()) is not None:
        usos.append(uso)


@contextmanager
def medir() -> Iterator[list[Uso]]:
    """Junta el uso de los pedidos hechos adentro del bloque (para `python -m app eval`)."""
    usos: list[Uso] = []
    marca = _medicion.set(usos)
    try:
        yield usos
    finally:
        _medicion.reset(marca)


class ProveedorTexto(Protocol):
    def completar_json(self, sistema: str, mensaje: str) -> object:
        """Respuesta del modelo como JSON ya leído (sin validar: lo valida quien la usa)."""
        ...


class ProveedorIA(ProveedorTexto, Protocol):
    def transcribir(self, audio: bytes, nombre_archivo: str, glosario: str) -> str:
        """El texto del audio. `glosario`: palabras que tiene que escribir bien (puede ser vacío)."""
        ...


class ConRespaldo:
    """Interpreta con `principal` y, si falla, con `respaldo`, que además transcribe los audios."""

    def __init__(self, principal: ProveedorTexto, respaldo: ProveedorIA) -> None:
        self.principal = principal
        self.respaldo = respaldo

    def completar_json(self, sistema: str, mensaje: str) -> object:
        try:
            return self.principal.completar_json(sistema, mensaje)
        except ErrorIA as e:
            log.warning("Falló la IA principal (%s): pruebo con el respaldo", e)
        return self.respaldo.completar_json(sistema, mensaje)

    def transcribir(self, audio: bytes, nombre_archivo: str, glosario: str) -> str:
        return self.respaldo.transcribir(audio, nombre_archivo, glosario)


_proveedor: ProveedorIA | None = None


def _groq() -> ProveedorIA:
    from app.ia.proveedor_groq import ProveedorGroq
    from app.infra.config import config

    return ProveedorGroq(config.groq_api_key, config.groq_modelo, config.groq_modelo_audio)


def _openrouter(esfuerzo: str | None = None) -> ProveedorTexto:
    from app.ia.proveedor_openrouter import ProveedorOpenRouter
    from app.infra.config import config

    return ProveedorOpenRouter(
        config.openrouter_api_key, config.openrouter_modelo, esfuerzo or config.openrouter_esfuerzo
    )


def armar() -> ProveedorIA:
    """El de la configuración: OpenRouter con Groq de respaldo, o Groq solo si no hay clave."""
    from app.infra.config import config

    return ConRespaldo(_openrouter(), _groq()) if config.openrouter_api_key else _groq()


def uno_solo(nombre: str, esfuerzo: str | None = None) -> ProveedorTexto:
    """Un proveedor sin respaldo ("openrouter" o "groq"), para medirlo con `python -m app eval`."""
    return _openrouter(esfuerzo) if nombre == "openrouter" else _groq()


def obtener() -> ProveedorIA:
    global _proveedor
    if _proveedor is None:
        _proveedor = armar()
    return _proveedor


def describir() -> str:
    """Qué IA se usa, para el log al arrancar."""
    from app.infra.config import config

    if config.openrouter_api_key:
        return (
            f"IA: OpenRouter ({config.openrouter_modelo}, esfuerzo {config.openrouter_esfuerzo}) "
            "con Groq de respaldo; audios en Groq"
        )
    return f"IA: Groq ({config.groq_modelo}); sin OPENROUTER_API_KEY"


def usar(proveedor: ProveedorIA | None) -> None:
    """Reemplaza el proveedor (por ejemplo, uno falso en los tests). None vuelve al de la configuración."""
    global _proveedor
    _proveedor = proveedor
