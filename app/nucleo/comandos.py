"""Comandos fijos que no pasan por la IA: ayuda, privacidad, borrar, borrar mis datos y
los del administrador.

Salvo los del administrador y la confirmación de "borrar mis datos", son atajos: lo mismo
se puede pedir con cualquier frase y llega por la IA a estas mismas funciones (principio 7
del plan, `modulos/comun/cuenta.py`)."""

import logging
import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.infra.config import config
from app.infra.marca import NOMBRE
from app.infra.modelos import Usuario
from app.infra.texto import sin_tildes
from app.nucleo import auditoria, invitaciones, usuarios
from app.nucleo.cuaderno import Cuaderno
from app.salidas.whatsapp import SEPARADOR as LINEA

log = logging.getLogger(__name__)

AYUDA = f"""🐄 *{NOMBRE.upper()}*
_Tu cuaderno de trabajo en el campo, por WhatsApp._

_Hablame como siempre, por audio o por escrito: no hace falta ninguna palabra exacta._

✍️ *Anotar*
      › Estoy en La Esperanza
      › Vacuné 20 vacas contra aftosa en el lote 3
      › En El Ombú hice tacto a 50 vaquillonas
      › Llovieron 35 mm

▶️ *Sesiones de trabajo*
      › Arranco manga en El Retiro
      › Empiezo siembra en el lote Los Pinos
      › Listo, terminamos

📌 *Pendientes*
      › Tengo que revisar las aguadas el martes
      › ¿Qué tengo pendiente?
      › Ya está lo de las aguadas

✏️ *Corregir o borrar*
      › A esas vaquillonas les di ivermectina
      › No eran 20, eran 25
      › Borrá la lluvia de La Pastora
      › Me equivoqué, sacá lo último
      › Omu en realidad es El Ombú

🔍 *Consultar*
      › ¿Qué tengo anotado?
      › ¿Qué hice en La Esperanza este mes?
      › ¿Cuántas vacas vacuné esta semana?

📄 *Archivos para reenviar*
      › Mandame un PDF de lo que hice este mes
      › Pasame el informe de La Pastora
      › Quiero la planilla en Excel de las vacunaciones

💲 *Precios oficiales*
      › ¿A cuánto está la soja y el maíz?
      › Precio del novillo

💊 *Productos en SENASA*
      › ¿La ivermectina está aprobada?

👤 *Tus campos y tus datos*
      › ¿Qué campos tengo cargados?
      › Mostrame mis datos
      › Quiero cambiar mi rubro
      › ¿Quién ve lo que anoto?

────────────
🔒 Lo que anotás es solo tuyo.

⚡ *Atajos* (escribí solo eso)
*borrar* → deshace lo último que anotaste
*mis campos* · *mis datos* · *privacidad*
*cerrar sesión* · *ayuda*
*borrar mis datos* → elimina todo lo tuyo"""

AYUDA_ADMIN = """

🔑 *Administrador*
*autorizar 5492494123456* → le da acceso
*quitar 5492494123456* → le saca el acceso
*autorizados* → lista de números con acceso
*invitar* → crea un código de invitación
*invitaciones* → códigos vigentes
*anular ANOTA-XXXX-XXXX* → anula un código
*modo prueba* → guarda tus mensajes para el set de evaluación
*fin modo prueba* → deja de guardarlos"""

PEDIR_AYUDA = {"ayuda", "help", "menu", "menú"}
DESHACER = {"borrar", "deshacer"}
VER_PRIVACIDAD = {"privacidad", "datos"}

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
        "      › Guardo tu número, tu nombre, rubro y localidad, y lo que anotás, solo para mostrártelo a vos.\n"
        "      › Nadie más ve tu cuaderno, ni siquiera quien tenga el mismo campo.\n"
        "      › Tus mensajes los interpreta una IA (OpenRouter y Groq) que no los guarda ni los usa para entrenar, y viajan por WhatsApp (Meta).\n"
        "      › No vendo ni comparto tus datos con nadie más.\n\n"
        "*Qué podés hacer*\n"
        "      › Ver todo lo tuyo: *mis datos* y _¿qué tengo anotado?_\n"
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
        f"      › tu cuaderno ({registros} registro{'s' if registros != 1 else ''}) y tus pendientes\n"
        "      › tus últimos mensajes con el bot\n"
        "      › tu número, tu nombre, rubro, localidad y matrícula\n\n"
        "También perdés el acceso: para volver a usarlo, el administrador te tiene que habilitar de nuevo.\n\n"
        f"{LINEA}\n"
        "Si estás seguro, mandá exactamente:\n*confirmo borrar mis datos*\n\n"
        "_Si no, ignorá este mensaje y no se borra nada._"
    )


def borrar_datos(db: Session, usuario: Usuario) -> str:
    registros = Cuaderno(db, usuario).cantidad()
    # Solo ids: después de esto no queda nada de la persona, salvo que borró sus datos.
    auditoria.registrar(
        db, auditoria.BORRAR_DATOS, actor=usuario.id, sobre=usuario.id, cuenta=usuario.cuenta_id, registros=registros
    )
    usuarios.eliminar(db, usuario)
    log.info("Usuario %s borró todos sus datos", usuario.id)
    return (
        "🗑️ *DATOS BORRADOS*\n\n"
        "Eliminé tu cuaderno, tus mensajes y tu número. No queda nada tuyo guardado.\n"
        f"Gracias por haber usado {NOMBRE} 👋"
    )


def admin(db: Session, texto: str, actor: int) -> str | None:
    """Comandos del administrador (`actor`: su id de usuario); None si el texto no es uno."""
    pedido = normalizar(texto)
    ahora = datetime.now(UTC)
    if pedido == "invitar":
        return invitaciones.invitar(db, actor, ahora)
    if pedido == "invitaciones":
        return invitaciones.listar(db, ahora)
    if pedido.startswith("anular "):
        return invitaciones.anular(db, texto, actor, ahora)
    if texto.lower() == "autorizados":
        lista = usuarios.autorizados(db)
        if not lista:
            return "Todavía no autorizaste a nadie."
        return "Números con acceso:\n" + "\n".join(
            f"• {u.telefono}" + (f" ({nombre})" if (nombre := u.nombre_completo or u.nombre) else "") for u in lista
        )
    m = re.match(r"^(autorizar|quitar)\s+(.+)$", texto, re.IGNORECASE)
    if not m:
        return None
    telefono = usuarios.normalizar_telefono(m.group(2))
    if telefono is None:
        return "No entendí el número. Escribilo con código de país, ej: *autorizar 5492494123456*"
    if m.group(1).lower() == "autorizar":
        usuarios.autorizar(db, telefono, actor)
        return f"✅ {telefono} ya puede usar {NOMBRE}."
    if not usuarios.quitar(db, telefono, actor):
        return f"{telefono} no tenía acceso."
    return f"🚫 Le saqué el acceso a {telefono}. Sus registros se conservan."
