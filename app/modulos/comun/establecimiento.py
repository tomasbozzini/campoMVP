"""Establecimiento: la persona avisa en qué campo está, para anotar ahí lo que siga."""

from typing import Annotated

from app.ia.esquemas import EsquemaAccion, texto
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto


class Establecimiento(EsquemaAccion):
    establecimiento: Annotated[str, texto(120)]  # obligatorio: sin nombre no hay nada que hacer


def manejar(ctx: Contexto, datos: Establecimiento) -> str:
    ctx.usuario.establecimiento_actual = datos.establecimiento
    return f"📍 *{datos.establecimiento}*\n\nListo, lo próximo que anotes queda guardado acá."


ACCION = Accion("establecimiento", Establecimiento, manejar)
