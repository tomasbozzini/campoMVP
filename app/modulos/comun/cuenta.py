"""Lo que tiene atajo escrito y también se pide hablando normal: ayuda, privacidad, mis
campos, mis datos, cambiar rubro, cambiar matrícula y borrar mis datos.

Principio 7 del plan: si el mensaje es exactamente el atajo ("mis campos"), responde el
núcleo sin IA; si no ("che, ¿qué campos tengo cargados?"), la IA reconoce el pedido y llega
acá, al mismo manejador, con la misma respuesta. `borrar` y `cerrar sesión` también tienen
atajo; sus acciones están en borrar.py y sesion.py.

"borrar mis datos" por la IA solo muestra el aviso: borrar exige escribir exacto
"confirmo borrar mis datos", que nunca pasa por la IA.
"""

from app.ia.esquemas import EsquemaAccion
from app.modulos.comun import campos
from app.nucleo import comandos, perfil
from app.nucleo.acceso import es_admin
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto


class Pedido(EsquemaAccion):
    pass  # no lleva datos: la intención alcanza


def ayuda(ctx: Contexto, _datos: Pedido) -> str:
    return comandos.ayuda(es_admin(ctx.usuario.telefono))


def privacidad(_ctx: Contexto, _datos: Pedido) -> str:
    return comandos.privacidad()


def mis_campos(ctx: Contexto, _datos: Pedido) -> str:
    return campos.mis_campos(ctx.cuaderno, ctx.usuario)


def mis_datos(ctx: Contexto, _datos: Pedido) -> str:
    return perfil.ver_datos(ctx)


def cambiar_rubro(ctx: Contexto, _datos: Pedido) -> str:
    return perfil.pedir_rubro(ctx)


def cambiar_matricula(ctx: Contexto, _datos: Pedido) -> str:
    return perfil.pedir_matricula(ctx)


def borrar_mis_datos(ctx: Contexto, _datos: Pedido) -> str:
    return comandos.pedir_borrar_datos(ctx.cuaderno)


ACCIONES = [
    Accion("ayuda", Pedido, ayuda),
    Accion("privacidad", Pedido, privacidad),
    Accion("mis_campos", Pedido, mis_campos),
    Accion("mis_datos", Pedido, mis_datos),
    Accion("cambiar_rubro", Pedido, cambiar_rubro),
    Accion("cambiar_matricula", Pedido, cambiar_matricula),
    Accion("borrar_mis_datos", Pedido, borrar_mis_datos),
]
