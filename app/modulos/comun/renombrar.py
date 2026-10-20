"""Renombrar, unir y borrar campos y lotes (pasos 8.7 y 8.7.1 del plan).

"Omu en realidad es El Ombú", "cambiale el nombre a Omu, se llama El Ombú", "uní Omu con El
Ombú", "el lote 3 de La Pastora se llama Los Pinos", "borrá el campo Prueba". Sin comando
escrito: se pide hablando. Borrar es otra intención (`borrar_campo`), con el mismo dato.

- El campo que cambia tiene que existir con ese nombre, o con el mismo sin el artículo del
  principio ("el omu" es Omu); no se busca uno parecido. Si no lo dice, es el de la sesión
  abierta o el actual. Los lotes, dentro de un mismo campo.
- Si el nombre nuevo no existe, cambia el nombre y lo anotado queda igual.
- Si existe, es una unión: pregunta antes (*sí* / *no*) y muestra qué pasa al que queda. La
  unión la hace `confirmar` con el *sí* (`Cuaderno.unir_establecimientos` / `unir_lotes`).
- Borrar pregunta siempre, mostrando lo que se borra. Un campo tiene que nombrarse; un lote
  sin campo es del de la sesión abierta o el actual.
"""

from typing import Annotated

from pydantic import Field

from app.ia.esquemas import Esquema, EsquemaAccion, SiNoVacio, texto
from app.infra.modelos import Establecimiento
from app.infra.texto import prolijo
from app.modulos.comun import confirmar
from app.modulos.comun.confirmar import nombre_lote, resumen_union
from app.modulos.comun.registros import Lote
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto
from app.nucleo.normalizar import normalizar_lote

SIN_NOMBRE = "🤔 No entendí cómo se tiene que llamar.\nProbá con algo como: _Omu en realidad es El Ombú_."
CUAL_CAMPO = "🤔 ¿A qué campo le cambio el nombre?\nDecímelo así: _Omu en realidad es El Ombú_."
SIN_CAMPOS = "📭 No tenés campos cargados."


class Cambio(Esquema):
    campo: Annotated[str | None, texto(120)] = None  # el que cambia; con lote, el campo del lote
    lote: Lote = None  # solo si cambia un lote: el que cambia o desaparece
    nuevo: Annotated[str | None, texto(120)] = None  # el nombre que queda


class Renombrar(EsquemaAccion):
    renombrar: Annotated[Cambio, SiNoVacio] = Field(default_factory=Cambio)


def _actual(ctx: Contexto) -> Establecimiento | None:
    sesion = ctx.cuaderno.sesion_abierta()
    return sesion.establecimiento if sesion is not None else ctx.usuario.establecimiento_actual


def _tus_campos(ctx: Contexto) -> list[str]:
    return [c.establecimiento.nombre for c in ctx.cuaderno.campos() if c.establecimiento is not None]


def _no_esta(ctx: Contexto, nombre: str) -> str:
    nombres = _tus_campos(ctx)
    tuyos = f"\n\nTus campos: {', '.join(nombres)}." if nombres else ""
    return f"🤔 No tenés ningún campo que se llame *{prolijo(nombre)}*.{tuyos}"


def _cual_borrar(ctx: Contexto) -> str:
    """ "Borrar campo" sin decir cuál: pregunta cuál, con sus campos. La respuesta va a la IA
    con la charla, como cualquier respuesta corta."""
    nombres = _tus_campos(ctx)
    if not nombres:
        return SIN_CAMPOS
    return (
        f"🤔 *¿Qué campo querés borrar?*\n\nTus campos: {', '.join(nombres)}.\n\n"
        f"Decímelo así: _borrá el campo {nombres[0]}_."
    )


def _campo(ctx: Contexto, cambio: Cambio, nuevo: str) -> str:
    cuaderno = ctx.cuaderno
    campo = cuaderno.establecimiento_nombrado(cambio.campo) if cambio.campo else _actual(ctx)
    if campo is None:
        return _no_esta(ctx, cambio.campo) if cambio.campo else CUAL_CAMPO
    otro = cuaderno.establecimiento_nombrado(nuevo)
    if otro is None or otro.id == campo.id:
        if campo.nombre == prolijo(nuevo):
            return f"👍 Tu campo ya se llama *{campo.nombre}*."
        antes = campo.nombre
        cuaderno.renombrar_establecimiento(campo, nuevo)
        return f"✏️ *CAMPO RENOMBRADO*\n\n*{antes}* ahora se llama *{campo.nombre}*. Lo anotado ahí sigue igual."
    contenido = cuaderno.contenido_establecimiento(campo, otro)
    iguales = ""
    if contenido.lotes_iguales:
        lotes = ", ".join(nombre_lote(n) for n in contenido.lotes_iguales)
        iguales = f"\n\n_Los lotes que se llaman igual en los dos se juntan: {lotes}._"
    pregunta = (
        f"🔗 *¿Uno {campo.nombre} con {otro.nombre}?*\n\n"
        f"Ya tenés el campo *{otro.nombre}*. Queda ese, con lo de *{campo.nombre}*:\n\n"
        f"{resumen_union(contenido, de_campo=True)}{iguales}"
    )
    return confirmar.pedir_union(cuaderno, confirmar.UNIR_CAMPOS, campo.id, otro.id, pregunta, ctx.ahora)


def _lote(ctx: Contexto, cambio: Cambio, nuevo: str) -> str:
    cuaderno = ctx.cuaderno
    if cambio.campo:
        campo = cuaderno.establecimiento_nombrado(cambio.campo)
        if campo is None:
            return _no_esta(ctx, cambio.campo)
    else:
        campo = _actual(ctx)
    donde = f"*{campo.nombre}*" if campo else "tus lotes sin campo"
    lote = cuaderno.lote_existente(cambio.lote, campo)
    if lote is None:
        return (
            f"🤔 No encontré el *{nombre_lote(cambio.lote or '')}* en {donde}.\nMandá *mis campos* para ver tus lotes."
        )
    nombre = normalizar_lote(nuevo)
    if not nombre:
        return SIN_NOMBRE
    otro = cuaderno.lote_existente(nombre, campo)
    if otro is None or otro.id == lote.id:
        if lote.nombre == nombre:
            return f"👍 El *{nombre_lote(lote.nombre)}* ya se llama así."
        antes = nombre_lote(lote.nombre)
        cuaderno.renombrar_lote(lote, nombre)
        return f"✏️ *LOTE RENOMBRADO*\n\nEl *{antes}* de {donde} ahora se llama *{nombre_lote(lote.nombre)}*."
    pregunta = (
        f"🔗 *¿Uno el {nombre_lote(lote.nombre)} con el {nombre_lote(otro.nombre)}?*\n\n"
        f"En {donde} ya tenés el *{nombre_lote(otro.nombre)}*. Queda ese, con lo del *{nombre_lote(lote.nombre)}*:\n\n"
        f"{resumen_union(cuaderno.contenido_lote(lote), de_campo=False)}"
    )
    return confirmar.pedir_union(cuaderno, confirmar.UNIR_LOTES, lote.id, otro.id, pregunta, ctx.ahora)


def _es_un_lote(ctx: Contexto, nombre: str, establecimiento: str | None) -> bool:
    """No hay un campo con ese nombre pero sí un lote ("cambiale el nombre al potrero grande"):
    la IA lo puso como campo. El lote se busca en el campo que nombra la acción
    ("establecimiento", como en "el potrero grande de El Ombú") o, si no, en el actual."""
    cuaderno = ctx.cuaderno
    if cuaderno.establecimiento_nombrado(nombre) is not None:
        return False
    donde = cuaderno.establecimiento_nombrado(establecimiento) if establecimiento else _actual(ctx)
    return cuaderno.lote_existente(nombre, donde) is not None


def manejar(ctx: Contexto, datos: Renombrar) -> str:
    cambio, nuevo = datos.renombrar, datos.renombrar.nuevo
    if not nuevo:
        return SIN_NOMBRE
    if not cambio.lote and cambio.campo and _es_un_lote(ctx, cambio.campo, datos.establecimiento):
        cambio = Cambio(lote=normalizar_lote(cambio.campo), nuevo=nuevo)
    if cambio.lote:
        # El campo del lote: a veces la IA lo pone en "establecimiento" ("el lote 3 de La Pastora").
        cambio = cambio.model_copy(update={"campo": cambio.campo or datos.establecimiento})
        return _lote(ctx, cambio, nuevo)
    return _campo(ctx, cambio, nuevo)


# --- Borrar un campo o un lote (paso 8.7.1) ----------------------------------------------


class Cual(Esquema):
    campo: Annotated[str | None, texto(120)] = None  # el que se borra; con lote, el campo del lote
    lote: Lote = None  # solo si se borra un lote


class BorrarCampo(EsquemaAccion):
    borrar_campo: Annotated[Cual, SiNoVacio] = Field(default_factory=Cual)


def borrar(ctx: Contexto, datos: BorrarCampo) -> str:
    """Siempre pregunta, mostrando lo que se borra; lo borra `confirmar` con el *sí*."""
    cuaderno = ctx.cuaderno
    cual = datos.borrar_campo
    campo_nombre, lote_nombre = cual.campo, cual.lote
    if not lote_nombre and campo_nombre and _es_un_lote(ctx, campo_nombre, datos.establecimiento):
        lote_nombre, campo_nombre = normalizar_lote(campo_nombre), None
    nombrado = campo_nombre or datos.establecimiento  # a veces la IA lo pone en "establecimiento"
    if nombrado:
        campo = cuaderno.establecimiento_nombrado(nombrado)
        if campo is None:
            return _no_esta(ctx, nombrado)
    elif lote_nombre:
        campo = _actual(ctx)
    else:
        return _cual_borrar(ctx)
    if lote_nombre:
        return _borrar_lote(ctx, lote_nombre, campo)
    assert campo is not None
    aca = ""
    if ctx.usuario.establecimiento_actual_id == campo.id:
        aca = "\n\n_Es el campo donde estás: vas a quedar sin campo actual._"
    pregunta = (
        f"🗑️ *¿Borro el campo {campo.nombre}?*\n\nSe borra con todo lo suyo:\n\n"
        f"{resumen_union(cuaderno.contenido_establecimiento(campo), de_campo=True)}{aca}"
    )
    return confirmar.pedir_baja(cuaderno, confirmar.BORRAR_CAMPO, campo.id, pregunta, ctx.ahora)


def _borrar_lote(ctx: Contexto, nombre: str, campo: Establecimiento | None) -> str:
    cuaderno = ctx.cuaderno
    donde = f"*{campo.nombre}*" if campo else "tus lotes sin campo"
    lote = cuaderno.lote_existente(nombre, campo)
    if lote is None:
        return f"🤔 No encontré el *{nombre_lote(nombre)}* en {donde}.\nMandá *mis campos* para ver tus lotes."
    de = f" de {campo.nombre}" if campo else ""
    pregunta = (
        f"🗑️ *¿Borro el {nombre_lote(lote.nombre)}{de}?*\n\nSe borra con sus registros y pendientes:\n\n"
        f"{resumen_union(cuaderno.contenido_lote(lote, para_borrar=True), de_campo=False)}"
    )
    return confirmar.pedir_baja(cuaderno, confirmar.BORRAR_LOTE, lote.id, pregunta, ctx.ahora)


ACCIONES = [Accion("renombrar_campo", Renombrar, manejar), Accion("borrar_campo", BorrarCampo, borrar)]
