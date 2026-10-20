"""Renombrar y unir campos y lotes (paso 8.7 del plan).

"Omu en realidad es El Ombú", "cambiale el nombre a Omu, se llama El Ombú", "uní Omu con El
Ombú", "el lote 3 de La Pastora se llama Los Pinos". Sin comando escrito: se pide hablando.

- El campo que cambia tiene que existir con ese nombre (no se busca uno parecido); si no lo
  dice, es el de la sesión abierta o el actual. Los lotes, dentro de un mismo campo.
- Si el nombre nuevo no existe, cambia el nombre y lo anotado queda igual.
- Si existe, es una unión: pregunta antes (*sí* / *no*) y muestra qué pasa al que queda. La
  unión la hace `confirmar` con el *sí* (`Cuaderno.unir_establecimientos` / `unir_lotes`).
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


class Cambio(Esquema):
    campo: Annotated[str | None, texto(120)] = None  # el que cambia; con lote, el campo del lote
    lote: Lote = None  # solo si cambia un lote: el que cambia o desaparece
    nuevo: Annotated[str | None, texto(120)] = None  # el nombre que queda


class Renombrar(EsquemaAccion):
    renombrar: Annotated[Cambio, SiNoVacio] = Field(default_factory=Cambio)


def _actual(ctx: Contexto) -> Establecimiento | None:
    sesion = ctx.cuaderno.sesion_abierta()
    return sesion.establecimiento if sesion is not None else ctx.usuario.establecimiento_actual


def _no_esta(ctx: Contexto, nombre: str) -> str:
    nombres = [c.establecimiento.nombre for c in ctx.cuaderno.campos() if c.establecimiento is not None]
    tuyos = f"\n\nTus campos: {', '.join(nombres)}." if nombres else ""
    return f"🤔 No tenés ningún campo que se llame *{prolijo(nombre)}*.{tuyos}"


def _campo(ctx: Contexto, cambio: Cambio, nuevo: str) -> str:
    cuaderno = ctx.cuaderno
    campo = cuaderno.establecimiento_existente(cambio.campo) if cambio.campo else _actual(ctx)
    if campo is None:
        return _no_esta(ctx, cambio.campo) if cambio.campo else CUAL_CAMPO
    otro = cuaderno.establecimiento_existente(nuevo)
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
        campo = cuaderno.establecimiento_existente(cambio.campo)
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


def _es_un_lote(ctx: Contexto, nombre: str) -> bool:
    """No hay un campo con ese nombre pero sí un lote, en el campo actual ("cambiale el nombre
    al potrero grande"): la IA lo puso como campo."""
    cuaderno = ctx.cuaderno
    return (
        cuaderno.establecimiento_existente(nombre) is None and cuaderno.lote_existente(nombre, _actual(ctx)) is not None
    )


def manejar(ctx: Contexto, datos: Renombrar) -> str:
    cambio, nuevo = datos.renombrar, datos.renombrar.nuevo
    if not nuevo:
        return SIN_NOMBRE
    if not cambio.lote and cambio.campo and _es_un_lote(ctx, cambio.campo):
        cambio = Cambio(lote=normalizar_lote(cambio.campo), nuevo=nuevo)
    if cambio.lote:
        # El campo del lote: a veces la IA lo pone en "establecimiento" ("el lote 3 de La Pastora").
        cambio = cambio.model_copy(update={"campo": cambio.campo or datos.establecimiento})
        return _lote(ctx, cambio, nuevo)
    return _campo(ctx, cambio, nuevo)


ACCION = Accion("renombrar_campo", Renombrar, manejar)
