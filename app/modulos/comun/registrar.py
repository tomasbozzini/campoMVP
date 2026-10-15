"""Registrar: anotar en el cuaderno lo que la persona cuenta que hizo o pasó."""

import uuid
from typing import Annotated

from app.ia.esquemas import EsquemaAccion, SoloObjetos
from app.infra.modelos import Evento
from app.modulos.comun.registros import CATEGORIAS, DatosEvento, fecha_valida
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto
from app.salidas import whatsapp as formato
from app.salidas.whatsapp import SEPARADOR as LINEA

NADA_CLARO = "🤔 No me quedó claro qué querés anotar.\nProbá con algo como: _vacuné 20 vacas en el lote 3_"


class Registrar(EsquemaAccion):
    # Un mensaje puede traer varios eventos ("nacieron 4 terneros y murió 1").
    eventos: Annotated[list[DatosEvento], SoloObjetos]


def heredar_contexto(eventos: list[DatosEvento]) -> None:
    """Completa el lote y la categoría de animal que el mensaje menciona una sola vez.

    "ayer nacieron 4 terneros en el lote 5 y murió 1" llega como dos eventos, y el
    segundo viene sin lote ni categoría. Si en todo el mensaje hay un único lote y una
    única categoría, son los que corresponden. Si hay más de uno, no adivinamos.
    """
    if len(eventos) < 2:
        return
    lotes = {e.lote for e in eventos if e.lote}
    categorias = {e.categoria_animal for e in eventos if e.categoria_animal}
    lote = next(iter(lotes)) if len(lotes) == 1 else None
    categoria = next(iter(categorias)) if len(categorias) == 1 else None
    for e in eventos:
        # Solo heredan los eventos que hablan de animales: una lluvia no pasa a ser
        # "del lote 5" porque en el mismo mensaje se haya nombrado un lote.
        if not (e.cantidad_animales or e.caravana):
            continue
        if lote and not e.lote and not e.lote_destino:
            e.lote = lote
        if categoria and not e.categoria_animal:
            e.categoria_animal = categoria


def manejar(ctx: Contexto, datos: Registrar) -> str:
    heredar_contexto(datos.eventos)
    usuario, cuaderno = ctx.usuario, ctx.cuaderno
    # Si el mensaje nombra un establecimiento, pasa a ser el actual (aunque no traiga nada
    # que se pueda anotar); si no, se usa el último que nombró.
    if datos.establecimiento and (nombrado := cuaderno.establecimiento(datos.establecimiento)):
        usuario.establecimiento_actual = nombrado
    validos = [e for e in datos.eventos if e.categoria in CATEGORIAS]
    if not validos:
        return NADA_CLARO
    establecimiento = usuario.establecimiento_actual
    mensaje_id = str(uuid.uuid4())  # une los eventos del mensaje para poder "borrar" todo junto
    guardados = [
        Evento(
            establecimiento=establecimiento,
            lote=cuaderno.lote(e.lote, establecimiento),
            lote_destino=cuaderno.lote(e.lote_destino, establecimiento),
            categoria=e.categoria,
            tipo=e.tipo or "otro",
            descripcion=e.descripcion,
            producto=e.producto,
            dosis=e.dosis,
            cantidad_animales=e.cantidad_animales,
            categoria_animal=e.categoria_animal,
            caravana=e.caravana,
            valor=e.valor,
            unidad=e.unidad,
            fecha_evento=fecha_valida(e.fecha_evento, ctx.hoy),
            confianza=e.confianza,
            mensaje_original=ctx.texto,
            mensaje_id=mensaje_id,
        )
        for e in validos
    ]
    cuaderno.agregar(guardados)
    donde = f"📍 {establecimiento.nombre}" if establecimiento else "📍 _sin establecimiento_"
    cantidad = f"{len(guardados)} registros" if len(guardados) > 1 else "1 registro"
    partes = [f"✅ *ANOTADO*\n{donde} · {cantidad}", formato.tarjetas(guardados, lugar=False)]
    if any(e.confianza == "baja" for e in guardados):
        partes.append(
            f"{LINEA}\n⚠️ No estoy seguro de haber entendido bien.\n_Si algo está mal, corregilo o mandá *borrar*._"
        )
    else:
        partes.append(f"{LINEA}\n_¿Algo mal? Corregilo o mandá *borrar*._")
    return "\n\n".join(partes)


ACCION = Accion("registrar", Registrar, manejar)
