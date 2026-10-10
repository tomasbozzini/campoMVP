"""Servidor del webhook de WhatsApp."""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError

from app import bot, config, llm, whatsapp
from app.db import SessionLocal, crear_tablas
from app.models import MensajeProcesado

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def _ciclo_de_vida(_app: FastAPI):
    crear_tablas()
    yield


app = FastAPI(title="Asistente de campo", lifespan=_ciclo_de_vida)


@app.get("/")
def salud() -> dict:
    return {"ok": True}


@app.get("/webhook")
def verificar_webhook(
    modo: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    desafio: str = Query(None, alias="hub.challenge"),
) -> Response:
    """Meta llama a este endpoint una vez al configurar el webhook."""
    if modo == "subscribe" and config.WA_VERIFY_TOKEN and token == config.WA_VERIFY_TOKEN:
        return Response(content=desafio, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@app.post("/webhook")
async def recibir_webhook(request: Request, tareas: BackgroundTasks) -> dict:
    cuerpo = await request.body()
    if not whatsapp.firma_valida(cuerpo, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Firma inválida")

    datos = json.loads(cuerpo or b"{}")
    for entrada in datos.get("entry", []):
        for cambio in entrada.get("changes", []):
            valor = cambio.get("value", {})
            nombres = {
                c.get("wa_id"): c.get("profile", {}).get("name") for c in valor.get("contacts", [])
            }
            for mensaje in valor.get("messages", []):
                # Respondemos 200 enseguida (si no, Meta reintenta) y procesamos aparte.
                tareas.add_task(procesar_mensaje, mensaje, nombres.get(mensaje.get("from")))
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


def procesar_mensaje(mensaje: dict, nombre: str | None) -> None:
    telefono = mensaje.get("from")
    wamid = mensaje.get("id")
    if not telefono or not wamid or _ya_procesado(wamid):
        return

    tipo = mensaje.get("type")
    prefijo = ""
    try:
        if tipo == "text":
            texto = mensaje["text"]["body"]
        elif tipo == "audio":
            with SessionLocal() as db:
                habilitado = bot.puede_usar_ia(db, telefono)
            if not habilitado:
                whatsapp.enviar_texto(telefono, bot.BIENVENIDA)
                return
            audio = whatsapp.descargar_media(mensaje["audio"]["id"])
            if len(audio) > config.MAX_AUDIO_BYTES:
                whatsapp.enviar_texto(telefono, "El audio es muy largo. Mandá audios más cortos, de a un tema por vez.")
                return
            texto = llm.transcribir(audio)
            prefijo = f"🎤 _{texto[:config.MAX_LARGO_MENSAJE]}_\n\n"
        else:
            whatsapp.enviar_texto(telefono, "Por ahora solo entiendo mensajes de texto y audios 🙏")
            return

        with SessionLocal() as db:
            respuesta = bot.manejar_mensaje(db, telefono, texto, nombre=nombre)
            db.commit()
    except Exception:
        log.exception("Error procesando mensaje %s", wamid)
        respuesta = "Uy, algo falló procesando tu mensaje. Probá de nuevo en un rato."

    whatsapp.enviar_texto(telefono, prefijo + respuesta)
