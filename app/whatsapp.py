"""Cliente de la WhatsApp Cloud API de Meta."""

import hashlib
import hmac
import logging

import httpx

from app import config

log = logging.getLogger(__name__)

LIMITE_TEXTO = 4096


def _url(path: str) -> str:
    return f"https://graph.facebook.com/{config.GRAPH_API_VERSION}/{path}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.WA_TOKEN}"}


def firma_valida(cuerpo: bytes, firma_header: str | None) -> bool:
    """Verifica que el webhook venga de Meta (header X-Hub-Signature-256)."""
    if not config.META_APP_SECRET:
        log.warning("META_APP_SECRET no configurado: no se verifica la firma del webhook")
        return True
    if not firma_header or not firma_header.startswith("sha256="):
        return False
    esperada = hmac.new(config.META_APP_SECRET.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, firma_header.removeprefix("sha256="))


def numero_para_envio(telefono: str) -> str:
    if config.WA_AR_QUITAR_9 and telefono.startswith("549"):
        return "54" + telefono[3:]
    return telefono


def enviar_texto(telefono: str, texto: str) -> None:
    for i in range(0, len(texto), LIMITE_TEXTO):
        r = httpx.post(
            _url(f"{config.WA_PHONE_NUMBER_ID}/messages"),
            headers=_headers(),
            json={
                "messaging_product": "whatsapp",
                "to": numero_para_envio(telefono),
                "type": "text",
                "text": {"body": texto[i : i + LIMITE_TEXTO]},
            },
            timeout=20,
        )
        if r.status_code >= 400:
            log.error("Error enviando mensaje a WhatsApp: %s %s", r.status_code, r.text)


def descargar_media(media_id: str) -> bytes:
    """Los audios llegan como un id: primero se pide la URL y después se descarga."""
    with httpx.Client(headers=_headers(), timeout=60) as cliente:
        info = cliente.get(_url(media_id))
        info.raise_for_status()
        archivo = cliente.get(info.json()["url"])
        archivo.raise_for_status()
        return archivo.content
