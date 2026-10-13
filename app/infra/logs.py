"""Logs sin datos personales: los números de teléfono salen enmascarados."""

import logging
import re

# Secuencias de 10 a 15 dígitos (un número de WhatsApp), sueltas o dentro de un texto.
_TELEFONO = re.compile(r"(?<!\d)(\d{3})\d{4,8}(\d{3})(?!\d)")


def enmascarar(texto: str) -> str:
    """'5492494123456' -> '549*******456'. Se ve el país y el final, no el número."""
    return _TELEFONO.sub(lambda m: m.group(1) + "*" * (len(m.group(0)) - 6) + m.group(2), texto)


class FormateadorSinTelefonos(logging.Formatter):
    """Enmascara el mensaje completo ya armado, incluidos los argumentos y los tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return enmascarar(super().format(record))


def configurar_logs(nivel: int = logging.INFO) -> None:
    manejador = logging.StreamHandler()
    manejador.setFormatter(FormateadorSinTelefonos("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    raiz = logging.getLogger()
    raiz.handlers = [manejador]
    raiz.setLevel(nivel)
    # Alembic cuenta cada paso interno; alcanza con sus avisos y errores.
    logging.getLogger("alembic").setLevel(logging.WARNING)
