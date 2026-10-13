"""Comandos fijos que no pasan por la IA: ayuda, privacidad, borrar, borrar mis datos y
los del administrador."""

import logging
import re

from sqlalchemy.orm import Session

from app.infra.config import config
from app.infra.modelos import Usuario
from app.infra.texto import sin_tildes
from app.nucleo import usuarios
from app.nucleo.cuaderno import Cuaderno
from app.salidas.whatsapp import SEPARADOR as LINEA

log = logging.getLogger(__name__)

AYUDA = """🐄 *TU ASISTENTE DE CAMPO*
_Tu cuaderno de trabajo, por WhatsApp._

✍️ *Anotar*
      › Estoy en La Esperanza
      › Vacuné 20 vacas contra aftosa en el lote 3
      › En El Ombú hice tacto a 50 vaquillonas
      › Llovieron 35 mm

✏️ *Corregir o borrar*
      › A esas vaquillonas les di ivermectina
      › No eran 20, eran 25
      › Borrá la lluvia de La Pastora

🔍 *Consultar*
      › ¿Qué tengo anotado?
      › ¿Qué hice en La Esperanza este mes?
      › ¿Cuántas vacas vacuné esta semana?

💲 *Precios oficiales*
      › ¿A cuánto está la soja y el maíz?
      › Precio del novillo

💊 *Productos en SENASA*
      › ¿La ivermectina está aprobada?

────────────
🎤 También podés mandar audios.
🔒 Lo que anotás es solo tuyo.

*borrar* → deshace lo último que anotaste
*privacidad* → cómo se usan tus datos
*borrar mis datos* → elimina todo lo tuyo
*ayuda* → muestra este menú"""

AYUDA_ADMIN = """

🔑 *Administrador*
*autorizar 5492494123456* → le da acceso
*quitar 5492494123456* → le saca el acceso
*autorizados* → lista de números con acceso"""

PEDIR_AYUDA = {"ayuda", "help", "menu", "menú"}
DESHACER = {"borrar", "deshacer"}
VER_PRIVACIDAD = {"privacidad", "mis datos", "datos"}

# Derecho de supresión (Ley 25.326): la persona puede borrar todo lo suyo desde el chat.
PEDIR_BORRAR_DATOS = {"borrar mis datos", "eliminar mis datos", "borrar mi cuenta", "eliminar mi cuenta"}
CONFIRMAR_BORRAR_DATOS = "confirmo borrar mis datos"


def normalizar(texto: str) -> str:
    """Para reconocer comandos escritos de cualquier forma: "¡Borrar mis datos!" -> "borrar mis datos"."""
    return " ".join(sin_tildes(texto.lower().strip(" !.¡¿?")).split())


def ayuda(es_admin: bool) -> str:
    return AYUDA + (AYUDA_ADMIN if es_admin else "")


def privacidad() -> str:
    texto = (
        "🔒 *TUS DATOS*\n\n"
        "      › Guardo tu número y lo que anotás, solo para mostrártelo a vos.\n"
        "      › Nadie más ve tu cuaderno, ni siquiera quien tenga el mismo campo.\n"
        "      › Tus mensajes los interpreta una IA (Groq) y viajan por WhatsApp (Meta).\n"
        "      › No vendo ni comparto tus datos con nadie más.\n\n"
        "*Qué podés hacer*\n"
        "      › Ver todo lo tuyo: _¿qué tengo anotado?_\n"
        "      › Corregir o borrar registros cuando quieras\n"
        "      › Borrar todo, incluido tu número: *borrar mis datos*"
    )
    if config.privacidad_url:
        texto += f"\n\n{LINEA}\n📄 Política completa:\n{config.privacidad_url}"
    return texto


def pedir_borrar_datos(cuaderno: Cuaderno) -> str:
    registros = cuaderno.cantidad()
    return (
        "⚠️ *BORRAR TODOS TUS DATOS*\n\n"
        "Se van a eliminar para siempre:\n"
        f"      › tu cuaderno ({registros} registro{'s' if registros != 1 else ''})\n"
        "      › tus últimos mensajes con el bot\n"
        "      › tu número y tu nombre de perfil\n\n"
        "También perdés el acceso: para volver a usarlo, el administrador te tiene que habilitar de nuevo.\n\n"
        f"{LINEA}\n"
        "Si estás seguro, mandá exactamente:\n*confirmo borrar mis datos*\n\n"
        "_Si no, ignorá este mensaje y no se borra nada._"
    )


def borrar_datos(db: Session, usuario: Usuario) -> str:
    Cuaderno(db, usuario.id).borrar_todo()
    db.delete(usuario)
    db.flush()
    log.info("Usuario %s borró todos sus datos", usuario.id)
    return (
        "🗑️ *DATOS BORRADOS*\n\n"
        "Eliminé tu cuaderno, tus mensajes y tu número. No queda nada tuyo guardado.\n"
        "Gracias por haber usado el asistente 👋"
    )


def admin(db: Session, texto: str) -> str | None:
    """Comandos del administrador; None si el texto no es uno."""
    if texto.lower() == "autorizados":
        lista = usuarios.autorizados(db)
        if not lista:
            return "Todavía no autorizaste a nadie."
        return "Números con acceso:\n" + "\n".join(
            f"• {u.telefono}" + (f" ({u.nombre})" if u.nombre else "") for u in lista
        )
    m = re.match(r"^(autorizar|quitar)\s+(.+)$", texto, re.IGNORECASE)
    if not m:
        return None
    telefono = usuarios.normalizar_telefono(m.group(2))
    if telefono is None:
        return "No entendí el número. Escribilo con código de país, ej: *autorizar 5492494123456*"
    if m.group(1).lower() == "autorizar":
        usuarios.autorizar(db, telefono)
        return f"✅ {telefono} ya puede usar el asistente."
    if not usuarios.quitar(db, telefono):
        return f"{telefono} no tenía acceso."
    return f"🚫 Le saqué el acceso a {telefono}. Sus registros se conservan."
