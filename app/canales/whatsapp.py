"""Cliente de la WhatsApp Cloud API de Meta."""

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.infra.config import config

log = logging.getLogger(__name__)

LIMITE_TEXTO = 4096


def _url(path: str) -> str:
    return f"https://graph.facebook.com/{config.graph_api_version}/{path}"


def _headers() -> dict[str, Any]:
    return {"Authorization": f"Bearer {config.wa_token}"}


def firma_valida(cuerpo: bytes, firma_header: str | None) -> bool:
    """Verifica que el webhook venga de Meta (header X-Hub-Signature-256).

    Con META_APP_SECRET configurado se verifica siempre, también en desarrollo. Sin él,
    solo se deja pasar en desarrollo (en producción el servidor ni siquiera arranca).
    """
    if not config.meta_app_secret:
        if config.es_produccion:
            return False
        log.warning("META_APP_SECRET no configurado: en desarrollo no se verifica la firma del webhook")
        return True
    if not firma_header or not firma_header.startswith("sha256="):
        return False
    esperada = hmac.new(config.meta_app_secret.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, firma_header.removeprefix("sha256="))


def numero_para_envio(telefono: str) -> str:
    if config.wa_ar_quitar_9 and telefono.startswith("549"):
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
        _url(f"{config.wa_phone_number_id}/messages"),
        headers=_headers(),
        json={"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": texto}},
        timeout=20,
    )


def _codigo_error(r: httpx.Response) -> int | None:
    try:
        codigo = r.json().get("error", {}).get("code")
        return codigo if isinstance(codigo, int) else None
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


# --- Entrada ----------------------------------------------------------------


@dataclass(frozen=True)
class MensajeEntrante:
    """Un mensaje de WhatsApp, ya sacado del formato del webhook de Meta."""

    telefono: str
    wamid: str  # id de Meta, para no procesar dos veces el mismo mensaje
    tipo: str  # "text", "audio", "image"...
    texto: str | None = None
    audio_id: str | None = None
    nombre: str | None = None  # nombre de perfil de WhatsApp
    timestamp: int = 0  # segundos, como lo informa Meta


def leer_webhook(datos: dict[str, Any]) -> list[MensajeEntrante]:
    """Los mensajes que trae un webhook. Se descartan los que no tienen remitente o id."""
    mensajes: list[MensajeEntrante] = []
    for entrada in datos.get("entry", []):
        for cambio in entrada.get("changes", []):
            valor = cambio.get("value", {})
            nombres = {c.get("wa_id"): c.get("profile", {}).get("name") for c in valor.get("contacts", [])}
            for m in valor.get("messages", []):
                telefono, wamid = m.get("from"), m.get("id")
                if not telefono or not wamid:
                    continue
                mensajes.append(
                    MensajeEntrante(
                        telefono=telefono,
                        wamid=wamid,
                        tipo=m.get("type", ""),
                        texto=(m.get("text") or {}).get("body"),
                        audio_id=(m.get("audio") or {}).get("id"),
                        nombre=nombres.get(telefono),
                        timestamp=int(m.get("timestamp") or 0),
                    )
                )
    return mensajes
