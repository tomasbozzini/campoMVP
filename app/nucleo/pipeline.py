"""El camino de un mensaje: recibe el texto de una persona y devuelve la respuesta.

    acceso → comandos fijos → límites → IA (interpreta) → acciones (el código decide)

El bot es un asistente PERSONAL: cada número de WhatsApp tiene su propio cuaderno. Lo que
anota un veterinario en los campos que recorre queda solo en su cuaderno; el dueño de un
campo anota en el suyo. Los datos nunca se comparten entre personas.

La IA solo clasifica: ningún texto escrito por ella llega al usuario. Todas las respuestas
las arman los manejadores de cada acción con datos de la base y textos fijos, así no puede
recomendar, inventar ni usarse como chat de uso general.
"""

import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.ia import interprete
from app.ia.esquemas import EsquemaAccion
from app.infra.config import config
from app.modulos.comun import borrar
from app.nucleo import acciones, alta, charla, comandos, invitaciones, perfil
from app.nucleo.acceso import es_admin, usuario_con_acceso
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto

log = logging.getLogger(__name__)

MAX_ACCIONES = 6
SEPARADOR = "\n\n━━━━━━━━━━━━━━━\n\n"  # entre pedidos distintos de un mismo mensaje

FUERA_DE_ALCANCE = """🚫 *Eso no lo puedo responder*

Puedo ayudarte con:
      ✍️ Anotar lo que hacés en el campo
      🔍 Consultar lo que anotaste
      💲 Precios oficiales de granos y hacienda
      💊 Verificar productos en SENASA

_No doy recomendaciones, indicaciones de uso ni precios de medicamentos._
Mandá *ayuda* para ver ejemplos."""
FUERA_PARCIAL = (
    "🚫 Lo demás que pediste no lo puedo responder.\n"
    "_No doy recomendaciones ni respondo temas que no sean de tu cuaderno, precios oficiales o SENASA._"
)
MUY_LARGO = "✋ El mensaje es muy largo.\nMandalo en partes más cortas, de a un tema por vez."
SIN_CUPO = "⏳ Llegaste al límite de mensajes por hoy.\nMañana podés seguir."
ERROR_IA = "😕 Uy, no pude procesar el mensaje.\nProbá de nuevo en un ratito."


def _hoy() -> date:
    return datetime.now(config.zona_horaria).date()


def manejar_mensaje(db: Session, telefono: str, texto: str, nombre: str | None = None, hoy: date | None = None) -> str:
    texto = texto.strip()
    alta.limpiar(db)
    usuario = usuario_con_acceso(db, telefono, nombre) or alta.en_curso(db, telefono)
    if usuario is None:
        return alta.sin_acceso(db, telefono, texto, nombre)
    ctx = Contexto(db, usuario, texto, hoy or _hoy())
    comando = comandos.normalizar(texto)
    if comando in comandos.PEDIR_BORRAR_DATOS:
        return comandos.pedir_borrar_datos(ctx.cuaderno)
    if comando == comandos.CONFIRMAR_BORRAR_DATOS:
        # Después de esto no se guarda nada más de esta persona, ni siquiera este mensaje.
        return comandos.borrar_datos(db, usuario)
    if perfil.falta(usuario) or not usuario.autorizado:
        # Primero las preguntas fijas del alta. Nada de esto va a la charla ni a la IA.
        return alta.preguntar(ctx, _respuesta_fija(texto, telefono))
    respuesta = _responder(ctx, telefono)
    if ctx.guardar_charla:
        charla.guardar(ctx.cuaderno, texto, respuesta)
    return respuesta


def _respuesta_fija(texto: str, telefono: str) -> str | None:
    """Los comandos que se responden igual durante el alta: ayuda y privacidad."""
    comando = texto.lower().strip(" !.¡")
    if comando in comandos.PEDIR_AYUDA:
        return comandos.ayuda(es_admin(telefono))
    if comando in comandos.VER_PRIVACIDAD:
        return comandos.privacidad()
    return None


def _responder(ctx: Contexto, telefono: str) -> str:
    texto = ctx.texto
    comando = texto.lower().strip(" !.¡")
    if (respuesta := borrar.resolver_pendiente(ctx.cuaderno, comando)) is not None:
        return respuesta
    if (respuesta := perfil.comando(ctx)) is not None:
        ctx.guardar_charla = False  # trae nombre, localidad, matrícula
        return respuesta
    if es_admin(telefono) and (respuesta := comandos.admin(ctx.db, texto, ctx.usuario.id)):
        return respuesta
    if comando in comandos.PEDIR_AYUDA:
        return comandos.ayuda(es_admin(telefono))
    if invitaciones.es_solo_un_codigo(texto):
        return alta.YA_TENES_ACCESO
    if comando in comandos.DESHACER:
        return borrar.borrar_ultimo(ctx.cuaderno)
    if comando in comandos.VER_PRIVACIDAD:
        return comandos.privacidad()

    if len(texto) > config.max_largo_mensaje:
        return MUY_LARGO
    if not ctx.cuaderno.consumir_cupo(ctx.hoy, config.limite_diario_ia):
        return SIN_CUPO

    try:
        interpretado = interprete.interpretar(texto, ctx.hoy, charla.historial(ctx.cuaderno))
    except Exception:
        log.exception("Error interpretando mensaje")
        return ERROR_IA
    return _ejecutar(ctx, _pedidos(interpretado))


def _pedidos(interpretado: object) -> list[dict[str, Any]]:
    """Los pedidos del mensaje ("¿cuánto está la soja y el maíz?", "anotá la lluvia y borrá la
    cosecha"). Se acepta también una respuesta de una sola acción, sin la lista."""
    if not isinstance(interpretado, dict):
        return []
    crudas = interpretado.get("acciones")
    lista = crudas if isinstance(crudas, list) else [interpretado]
    return [a for a in lista if isinstance(a, dict)][:MAX_ACCIONES]


def _ejecutar(ctx: Contexto, pedidos: list[dict[str, Any]]) -> str:
    varios = len(pedidos) > 1
    respuestas: list[str] = []
    hubo_fuera = False
    omitidas: list[tuple[Accion, EsquemaAccion]] = []
    # Acciones que se responden juntas: dónde va su respuesta y qué datos se juntaron.
    juntas: dict[str, tuple[Accion, int, list[EsquemaAccion]]] = {}

    for pedido in pedidos:
        accion = acciones.buscar(pedido.get("intencion"))
        datos = acciones.validar(accion, pedido) if accion else None
        if accion is None or datos is None:
            hubo_fuera = True
            continue
        if varios and accion.se_omite_si_hay_otras:
            omitidas.append((accion, datos))  # "hola, ¿cuánto está la soja?": se responde solo lo que pide
            continue
        if accion.juntar and accion.se_junta(datos):
            if accion.intencion not in juntas:
                juntas[accion.intencion] = (accion, len(respuestas), [])
                respuestas.append("")
            juntas[accion.intencion][2].append(datos)
            continue
        respuestas.append(accion.manejar(ctx, datos))

    for accion, posicion, lista in juntas.values():
        if accion.juntar:
            respuestas[posicion] = accion.juntar(ctx, lista)
    if not respuestas:
        if not hubo_fuera and omitidas:
            accion, datos = omitidas[0]
            return accion.manejar(ctx, datos)
        return FUERA_DE_ALCANCE
    if hubo_fuera:
        respuestas.append(FUERA_PARCIAL)
    return SEPARADOR.join(respuestas)
