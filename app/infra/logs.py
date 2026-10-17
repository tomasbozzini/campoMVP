"""Logs sin datos personales.

- Los números de teléfono salen enmascarados, estén donde estén (también en tracebacks).
- uvicorn (sus errores y el access log) pasa por el mismo enmascarado, y el access log no
  muestra el query string: el GET /webhook de Meta trae el token de verificación.
- El código no loguea el texto de los mensajes ni el wamid (en base64 lleva el teléfono).
  Los errores de la base no muestran los parámetros (`hide_parameters`, en app/infra/db.py)
  y los de la IA, solo el tipo y el código de estado (app/ia/proveedor_*.py). De cada
  pedido a la IA se loguea quién respondió, los tokens, el costo y la demora.
"""

import logging
import re
import sys
from typing import TextIO

# Secuencias de 10 a 15 dígitos (un número de WhatsApp en formato E.164), sueltas o dentro
# de un texto.
_TELEFONO = re.compile(r"(?<!\d)(\d{3})\d{4,9}(\d{3})(?!\d)")

FORMATO = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def enmascarar(texto: str) -> str:
    """'5492494123456' -> '549*******456'. Se ve el país y el final, no el número."""
    return _TELEFONO.sub(lambda m: m.group(1) + "*" * (len(m.group(0)) - 6) + m.group(2), texto)


class FormateadorSinTelefonos(logging.Formatter):
    """Enmascara el mensaje completo ya armado, incluidos los argumentos y los tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return enmascarar(super().format(record))


class _SalidaDeErrores(logging.StreamHandler):  # type: ignore[type-arg]
    """Escribe en el sys.stderr de cada momento y no en el que había al configurar los logs
    (los tests lo reemplazan). Si escribiera en uno ya cerrado, logging volcaría el mensaje
    sin formatear, con los teléfonos a la vista."""

    @property
    def stream(self) -> TextIO:
        return sys.stderr

    @stream.setter
    def stream(self, _valor: TextIO) -> None:
        pass


class _SinQueryString(logging.Filter):
    """El access log de uvicorn sin el query string de la ruta."""

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn loguea: '%s - "%s %s HTTP/%s" %d' (cliente, método, ruta, versión, estado)
        if isinstance(record.args, tuple) and len(record.args) == 5:
            cliente, metodo, ruta, version, estado = record.args
            record.args = (cliente, metodo, str(ruta).split("?", 1)[0], version, estado)
        return True


def configurar_logs(nivel: int = logging.INFO) -> None:
    manejador = _SalidaDeErrores()
    manejador.setFormatter(FormateadorSinTelefonos(FORMATO))
    raiz = logging.getLogger()
    raiz.handlers = [manejador]
    raiz.setLevel(nivel)
    # Alembic cuenta cada paso interno; alcanza con sus avisos y errores.
    logging.getLogger("alembic").setLevel(logging.WARNING)
    # httpx anota cada pedido a Groq y a Meta: ensucia el chat de la terminal, y la descarga
    # de un audio muestra la URL firmada del archivo. Alcanza con sus avisos y errores.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # uvicorn arma sus propios handlers antes de cargar la app: se los sacamos para que sus
    # mensajes salgan por el de arriba, con el mismo formato y enmascarados.
    for nombre in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        registro = logging.getLogger(nombre)
        registro.handlers = []
        registro.propagate = True
    acceso = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _SinQueryString) for f in acceso.filters):
        acceso.addFilter(_SinQueryString())
