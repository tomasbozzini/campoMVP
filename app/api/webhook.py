"""Webhook de WhatsApp: Meta llama acá con cada mensaje que recibe el número del bot."""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError

from app.canales import whatsapp
from app.canales.whatsapp import MensajeEntrante
from app.ia import interprete
from app.infra.config import config
from app.infra.db import SessionLocal
from app.infra.modelos import MensajeProcesado
from app.nucleo import acceso, pipeline

log = logging.getLogger(__name__)

rutas = APIRouter()

AUDIO_LARGO = "✋ El audio es muy largo.\nMandá audios más cortos, de a un tema por vez."
TIPO_NO_SOPORTADO = "Por ahora solo entiendo mensajes de texto y audios 🙏"
ERROR = "😕 Uy, algo falló procesando tu mensaje.\nProbá de nuevo en un rato."


@rutas.get("/webhook")
def verificar_webhook(
    modo: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    desafio: str = Query(None, alias="hub.challenge"),
) -> Response:
    """Meta llama a este endpoint una vez al configurar el webhook."""
    if modo == "subscribe" and config.wa_verify_token and token == config.wa_verify_token:
        return Response(content=desafio, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@rutas.post("/webhook")
async def recibir_webhook(request: Request, tareas: BackgroundTasks) -> dict:
    cuerpo = await request.body()
    if not whatsapp.firma_valida(cuerpo, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Firma inválida")
    # Respondemos 200 enseguida (si no, Meta reintenta) y procesamos aparte.
    for mensaje in whatsapp.leer_webhook(json.loads(cuerpo or b"{}")):
        tareas.add_task(procesar_mensaje, mensaje)
    return {"ok": True}


def _ya_procesado(wamid: str) -> bool:
    with SessionLocal() as db:
        try:
            db.add(MensajeProcesado(wamid=wamid))
            db.commit()
            return False
        except IntegrityError:
            db.rollback()
            return True


def procesar_mensaje(mensaje: MensajeEntrante) -> None:
    if _ya_procesado(mensaje.wamid):
        return
    telefono = mensaje.telefono
    prefijo = ""
    try:
        if mensaje.tipo == "text" and mensaje.texto is not None:
            texto = mensaje.texto
        elif mensaje.tipo == "audio" and mensaje.audio_id:
            with SessionLocal() as db:
                habilitado = acceso.puede_usar_ia(db, telefono)
            if not habilitado:
                whatsapp.enviar_texto(telefono, acceso.NO_AUTORIZADO)
                return
            audio = whatsapp.descargar_media(mensaje.audio_id)
            if len(audio) > config.max_audio_bytes:
                whatsapp.enviar_texto(telefono, AUDIO_LARGO)
                return
            texto = interprete.transcribir(audio)
            prefijo = f"🎤 _{texto[: config.max_largo_mensaje]}_\n\n"
        else:
            whatsapp.enviar_texto(telefono, TIPO_NO_SOPORTADO)
            return

        with SessionLocal() as db:
            respuesta = pipeline.manejar_mensaje(db, telefono, texto, nombre=mensaje.nombre)
            db.commit()
    except Exception:
        log.exception("Error procesando mensaje %s", mensaje.wamid)
        respuesta = ERROR

    whatsapp.enviar_texto(telefono, prefijo + respuesta)
