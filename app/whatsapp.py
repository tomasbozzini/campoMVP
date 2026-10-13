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


def _otra_forma_argentina(numero: str) -> str | None:
    """549XXXXXXXXXX <-> 54XXXXXXXXXX. WhatsApp manda los celulares argentinos con el 9,
    pero la lista de destinatarios de prueba de Meta a veces los guarda sin él."""
    if numero.startswith("549"):
        return "54" + numero[3:]
    if numero.startswith("54") and len(numero) == 12:
        return "549" + numero[2:]
    return None


# Meta: "Recipient phone number not in allowed list" (número de prueba sin ese destinatario)
NO_PERMITIDO = 131030


def _post_mensaje(numero: str, texto: str) -> httpx.Response:
    return httpx.post(
        _url(f"{config.WA_PHONE_NUMBER_ID}/messages"),
        headers=_headers(),
        json={"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": texto}},
        timeout=20,
    )


def _codigo_error(r: httpx.Response) -> int | None:
    try:
        return r.json().get("error", {}).get("code")
    except ValueError:
        return None


def enviar_texto(telefono: str, texto: str) -> None:
    numero = numero_para_envio(telefono)
    for i in range(0, len(texto), LIMITE_TEXTO):
        parte = texto[i : i + LIMITE_TEXTO]
        r = _post_mensaje(numero, parte)
        if _codigo_error(r) == NO_PERMITIDO and (otro := _otra_forma_argentina(numero)):
            r2 = _post_mensaje(otro, parte)
            if r2.status_code < 400:
                log.info("Meta aceptó %s en vez de %s; se usa ese formato", otro, numero)
                numero = otro
                continue
        if r.status_code >= 400:
            log.error(
                "Error enviando mensaje a WhatsApp al número %s: %s %s. Si el código es 131030, "
                "agregá ese número en Meta > WhatsApp > API Setup > To.",
                numero,
                r.status_code,
                r.text,
            )


def descargar_media(media_id: str) -> bytes:
    """Los audios llegan como un id: primero se pide la URL y después se descarga."""
    with httpx.Client(headers=_headers(), timeout=60) as cliente:
        info = cliente.get(_url(media_id))
        info.raise_for_status()
        archivo = cliente.get(info.json()["url"])
        archivo.raise_for_status()
        return archivo.content
