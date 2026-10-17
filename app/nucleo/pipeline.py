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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app import modulos
from app.ia import interprete
from app.ia.esquemas import EsquemaAccion
from app.ia.proveedor import IASaturada
from app.infra.config import config
from app.modulos.comun import borrar, campos, confirmar
from app.nucleo import acciones, alta, charla, comandos, invitaciones, perfil, sesiones
from app.nucleo.acceso import es_admin, usuario_con_acceso
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Adjunto, Contexto

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
DEMANDA = "⏳ Estoy con mucha demanda, probá de nuevo en un minuto."


def _hoy() -> date:
    return datetime.now(config.zona_horaria).date()


def _ahora() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Respuesta:
    """El texto que se le contesta a la persona y los archivos que van después."""

    texto: str
    adjuntos: list[Adjunto] = field(default_factory=list)


def manejar_mensaje(db: Session, telefono: str, texto: str, nombre: str | None = None, hoy: date | None = None) -> str:
    """Solo el texto de la respuesta (los tests y lo que no manda archivos)."""
    return atender(db, telefono, texto, nombre, hoy).texto


def atender(db: Session, telefono: str, texto: str, nombre: str | None = None, hoy: date | None = None) -> Respuesta:
    texto = texto.strip()
    alta.limpiar(db)
    usuario = usuario_con_acceso(db, telefono, nombre) or alta.en_curso(db, telefono)
    if usuario is None:
        return Respuesta(alta.sin_acceso(db, telefono, texto, nombre))
    ctx = Contexto(db, usuario, texto, hoy or _hoy(), _ahora())
    comando = comandos.normalizar(texto)
    if comando in comandos.PEDIR_BORRAR_DATOS:
        return Respuesta(comandos.pedir_borrar_datos(ctx.cuaderno))
    if comando == comandos.CONFIRMAR_BORRAR_DATOS:
        # Después de esto no se guarda nada más de esta persona, ni siquiera este mensaje.
        return Respuesta(comandos.borrar_datos(db, usuario))
    if perfil.falta(usuario) or not usuario.autorizado:
        # Primero las preguntas fijas del alta. Nada de esto va a la charla ni a la IA.
        return Respuesta(alta.preguntar(ctx, _respuesta_fija(texto, telefono)))
    # Si la sesión llevaba 12 horas sin mensajes, se cierra antes de atender este mensaje.
    cerrada = sesiones.al_escribir(ctx.cuaderno, ctx.ahora)
    respuesta = _responder(ctx, telefono)
    if cerrada:
        respuesta = cerrada + SEPARADOR + respuesta
    if ctx.guardar_charla:
        charla.guardar(ctx.cuaderno, texto, respuesta)
    return Respuesta(respuesta, ctx.adjuntos)


def _respuesta_fija(texto: str, telefono: str) -> str | None:
    """Los comandos que se responden igual durante el alta: ayuda y privacidad."""
    comando = comandos.normalizar(texto)
    if comando in comandos.PEDIR_AYUDA:
        return comandos.ayuda(es_admin(telefono))
    if comando in comandos.VER_PRIVACIDAD:
        return comandos.privacidad()
    return None


def _atajo(ctx: Contexto, telefono: str) -> str | None:
    """Los atajos: si el mensaje es exactamente el comando, se responde sin IA. Pedidos con
    otras palabras llegan por la IA a los mismos manejadores (principio 7 del plan)."""
    comando = comandos.normalizar(ctx.texto)
    if comando in comandos.PEDIR_AYUDA:
        return comandos.ayuda(es_admin(telefono))
    if comando in comandos.DESHACER:
        return borrar.borrar_ultimo(ctx.cuaderno, ctx.hoy)
    if comando in campos.PEDIR:
        return campos.mis_campos(ctx.cuaderno, ctx.usuario)
    if comando in sesiones.CERRAR:
        return sesiones.cerrar_pedido(ctx)
    if comando in comandos.VER_PRIVACIDAD:
        return comandos.privacidad()
    return None


def _responder(ctx: Contexto, telefono: str) -> str:
    texto = ctx.texto
    if (respuesta := confirmar.resolver(ctx.cuaderno, texto, ctx.ahora)) is not None:
        return respuesta
    if (respuesta := perfil.comando(ctx)) is not None:
        return respuesta
    if es_admin(telefono) and (respuesta := comandos.admin(ctx.db, texto, ctx.usuario.id)):
        return respuesta
    if invitaciones.es_solo_un_codigo(texto):
        return alta.YA_TENES_ACCESO
    if (respuesta := _atajo(ctx, telefono)) is not None:
        return respuesta

    if len(texto) > config.max_largo_mensaje:
        return MUY_LARGO
    if not ctx.cuaderno.consumir_cupo(ctx.hoy, config.limite_diario_ia):
        return SIN_CUPO

    suyos = modulos.del_rubro(ctx.usuario.rubro)
    try:
        interpretado = interprete.interpretar(
            texto, ctx.hoy, charla.historial(ctx.cuaderno), partes=modulos.partes(suyos)
        )
    except IASaturada as e:
        # Límite, sin saldo o sin respuesta: no es culpa del mensaje. El error solo trae
        # el tipo y el código, sin el texto de la persona.
        log.warning("IA con mucha demanda: %s", e)
        ctx.cuaderno.devolver_cupo(ctx.hoy)  # un mensaje que no se atendió no cuenta
        return DEMANDA
    except Exception:
        log.exception("Error interpretando mensaje")
        ctx.cuaderno.devolver_cupo(ctx.hoy)
        return ERROR_IA
    return _ejecutar(ctx, _pedidos(interpretado), suyos)


def _pedidos(interpretado: object) -> list[dict[str, Any]]:
    """Los pedidos del mensaje ("¿cuánto está la soja y el maíz?", "anotá la lluvia y borrá la
    cosecha"). Se acepta también una respuesta de una sola acción, sin la lista."""
    if not isinstance(interpretado, dict):
        return []
    crudas = interpretado.get("acciones")
    lista = crudas if isinstance(crudas, list) else [interpretado]
    return [a for a in lista if isinstance(a, dict)][:MAX_ACCIONES]


def _ejecutar(ctx: Contexto, pedidos: list[dict[str, Any]], suyos: list[str]) -> str:
    """Ejecuta los pedidos. Uno de un módulo que la persona no tiene se trata como fuera de
    alcance, aunque la IA lo devuelva: su prompt no lo ofrecía."""
    varios = len(pedidos) > 1
    respuestas: list[str] = []
    hubo_fuera = False
    omitidas: list[tuple[Accion, EsquemaAccion]] = []
    # Acciones que se responden juntas: dónde va su respuesta y qué datos se juntaron.
    juntas: dict[str, tuple[Accion, int, list[EsquemaAccion]]] = {}

    for pedido in pedidos:
        accion = acciones.buscar(pedido.get("intencion"))
        if accion is not None and accion.modulo not in suyos:
            accion = None
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
