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


def _sin_sesion(ctx: Contexto) -> bool:
    return ctx.cuaderno.sesion_abierta() is None


ACCIONES = [
    Accion("abrir_sesion", AbrirSesion, abrir),
    # "Vacuné 30 terneros y terminamos" o "Terminamos lote vaquillonas San Pedro: 88 preñadas…"
    # sin sesión abierta: se responde lo otro, sin "no tenés ninguna sesión abierta" (paso 3 de
    # la etapa 2). "Terminamos" solo, sí lo responde.
    Accion("cerrar_sesion", CerrarSesion, cerrar, se_omite_si_hay_otras=_sin_sesion),
]
