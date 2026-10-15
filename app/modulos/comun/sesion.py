"""Abrir y cerrar una sesión de trabajo ("arranco manga en El Retiro", "terminamos").

Las reglas de las sesiones están en app/nucleo/sesiones.py.
"""

from typing import Annotated

from pydantic import Field

from app.ia.esquemas import Esquema, EsquemaAccion, SiNoVacio, texto
from app.modulos.comun.registros import Lote
from app.nucleo import sesiones
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto


class DatosSesion(Esquema):
    lote: Lote = None
    actividad: Annotated[str | None, texto(60, minuscula=True)] = None  # "manga", "siembra", "tacto vaquillonas"


class AbrirSesion(EsquemaAccion):
    sesion: Annotated[DatosSesion, SiNoVacio] = Field(default_factory=DatosSesion)


class CerrarSesion(EsquemaAccion):
    pass


def abrir(ctx: Contexto, datos: AbrirSesion) -> str:
    return sesiones.abrir(ctx, datos.establecimiento, datos.sesion.lote, datos.sesion.actividad)


def cerrar(ctx: Contexto, _datos: CerrarSesion) -> str:
    return sesiones.cerrar_pedido(ctx)


ACCIONES = [
    Accion("abrir_sesion", AbrirSesion, abrir),
    Accion("cerrar_sesion", CerrarSesion, cerrar),
]
