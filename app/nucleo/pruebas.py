"""Modo prueba del administrador (paso 9a del plan).

`modo prueba` / `fin modo prueba`: comandos exactos y escritos, solo en el número del
administrador (no pasan por la IA). Mientras está prendido, cada mensaje suyo que va a la IA se
guarda con la charla y la pregunta abierta que vio la IA, el JSON que devolvió y la respuesta
del bot, para revisarlo con `python -m app eval revisar` y sumarlo al set de evaluación. De un
audio se guarda solo la transcripción. Los mensajes que no van a la IA no se guardan.
"""

from collections.abc import Sequence

from sqlalchemy import func, select

from app.infra.modelos import Prueba
from app.nucleo.contexto import Contexto

PRENDER, APAGAR = "modo prueba", "fin modo prueba"

PRENDIDO = (
    "🧪 *MODO PRUEBA*\n\n"
    "Desde ahora guardo cada mensaje tuyo que va a la IA: lo que entendió (el JSON) y lo que te "
    "respondí. De los audios, solo la transcripción.\n\n"
    "Para terminar: *fin modo prueba*."
)
YA_PRENDIDO = "🧪 El modo prueba ya está prendido.\nPara terminar: *fin modo prueba*."
NO_ESTABA = "🧪 El modo prueba no estaba prendido.\nPara empezar: *modo prueba*."


def comando(ctx: Contexto, pedido: str) -> str | None:
    """`pedido`: el texto normalizado (`comandos.normalizar`). None si no es uno de estos.
    No van a la charla: no son parte de la conversación que se prueba."""
    usuario = ctx.usuario
    if pedido in (PRENDER, APAGAR):
        ctx.guardar_charla = False
    if pedido == PRENDER:
        if usuario.modo_prueba:
            return YA_PRENDIDO
        usuario.modo_prueba = True
        return PRENDIDO
    if pedido == APAGAR:
        if not usuario.modo_prueba:
            return NO_ESTABA
        usuario.modo_prueba = False
        cuantas = ctx.db.scalar(select(func.count(Prueba.id)).where(Prueba.usuario_id == usuario.id)) or 0
        guardados = "1 mensaje guardado" if cuantas == 1 else f"{cuantas} mensajes guardados"
        return (
            f"🧪 *MODO PRUEBA TERMINADO*\n\nHay {guardados} en modo prueba.\n"
            "Los que no revisaste salen en la compu con: _python -m app eval revisar_"
        )
    return None


def anotar(ctx: Contexto, historial: Sequence[tuple[str, str]], interpretado: object) -> None:
    """Lo que vio y devolvió la IA, si el modo prueba está prendido. Se guarda con la respuesta."""
    if ctx.usuario.modo_prueba:
        ctx.prueba = {
            "historial": [[rol, texto] for rol, texto in historial],
            "pregunta": ctx.pregunta_abierta,
            "interpretacion": interpretado,
        }


def guardar(ctx: Contexto, es_admin: bool, respuesta: str, audio: bool) -> None:
    """Solo si el número sigue siendo administrador: si salió de la lista, no se guarda."""
    if ctx.prueba is None or not es_admin:
        return
    ctx.db.add(
        Prueba(usuario_id=ctx.usuario.id, texto=ctx.texto, audio=audio, hoy=ctx.hoy, respuesta=respuesta, **ctx.prueba)
    )
    ctx.db.flush()
