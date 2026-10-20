"""Códigos de invitación: los crea un administrador con "invitar" y sirven para darse de alta.

Un código sirve para una sola persona y vence a los 7 días; se puede anular. Es difícil de
adivinar: 8 caracteres al azar de un alfabeto de 31 (unas 850.000 millones de
combinaciones), y además hay un límite de intentos fallidos por número (app/nucleo/alta.py).
"""

import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.infra.config import config
from app.infra.modelos import Invitacion, Solicitud
from app.nucleo import auditoria, usuarios
from app.salidas.whatsapp import SEPARADOR as LINEA

# Sin 0/O ni 1/I/L, que se confunden al copiarlos a mano.
ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
DIAS_VIGENCIA = 7
# Los nuevos son ANOTA-XXXX-XXXX; los CAMPO- que se dieron antes del paso 8.6 siguen sirviendo.
PREFIJO = "ANOTA"
_CODIGO = re.compile(r"\b(ANOTA|CAMPO)[\s-]*([A-Z0-9]{4})[\s-]*([A-Z0-9]{4})\b", re.IGNORECASE)


def en_utc(momento: datetime) -> datetime:
    """SQLite devuelve las fechas sin zona horaria: se guardan siempre en UTC."""
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def generar() -> str:
    def bloque() -> str:
        return "".join(secrets.choice(ALFABETO) for _ in range(4))

    return f"{PREFIJO}-{bloque()}-{bloque()}"


def buscar_codigo(texto: str) -> str | None:
    """El código que trae el mensaje, escrito como sea ("anota 7k3p 9xq2"); None si no trae uno."""
    m = _CODIGO.search(texto)
    return f"{m.group(1).upper()}-{m.group(2).upper()}-{m.group(3).upper()}" if m else None


def es_solo_un_codigo(texto: str) -> bool:
    return _CODIGO.fullmatch(texto.strip(" .!")) is not None


def link(codigo: str) -> str | None:
    """wa.me/<número del bot>?text=<código>: abre el chat con el código ya escrito."""
    numero = re.sub(r"\D", "", config.wa_numero_bot)
    return f"https://wa.me/{numero}?text={codigo}" if numero else None


def crear(db: Session, actor: int, ahora: datetime) -> Invitacion:
    codigo = generar()
    while db.scalar(select(Invitacion.id).where(Invitacion.codigo == codigo)) is not None:
        codigo = generar()
    invitacion = Invitacion(codigo=codigo, creado=ahora, vence=ahora + timedelta(days=DIAS_VIGENCIA), creada_por=actor)
    db.add(invitacion)
    db.flush()
    auditoria.registrar(db, auditoria.INVITAR, actor=actor, invitacion=invitacion.id)
    return invitacion


def tomar(db: Session, codigo: str, ahora: datetime) -> Invitacion | None:
    """Marca el código como usado si está vigente. Es una sola operación en la base: si dos
    números lo mandan a la vez, solo uno se lo queda."""
    resultado = db.execute(
        update(Invitacion)
        .where(
            Invitacion.codigo == codigo,
            Invitacion.usada.is_(None),
            Invitacion.anulada.is_(None),
            Invitacion.vence > ahora,
        )
        .values(usada=ahora)
        .execution_options(synchronize_session=False)
    )
    if getattr(resultado, "rowcount", 0) != 1:
        return None
    return db.scalar(select(Invitacion).where(Invitacion.codigo == codigo))


def vigentes(db: Session, ahora: datetime) -> list[Invitacion]:
    q = select(Invitacion).where(Invitacion.usada.is_(None), Invitacion.anulada.is_(None), Invitacion.vence > ahora)
    return list(db.scalars(q.order_by(Invitacion.vence)).all())


# --- Comandos del administrador ----------------------------------------------


def _dia(momento: datetime) -> str:
    return en_utc(momento).astimezone(config.zona_horaria).strftime("%d/%m/%Y")


def invitar(db: Session, actor: int, ahora: datetime) -> str:
    invitacion = crear(db, actor, ahora)
    texto = (
        "🎟️ *INVITACIÓN*\n\n"
        f"Código: {invitacion.codigo}\n"
        f"Vence el {_dia(invitacion.vence)}. Sirve para una sola persona.\n\n"
        f"{LINEA}\n"
    )
    enlace = link(invitacion.codigo)
    if enlace:
        return texto + f"Reenviale este link a quien quieras invitar (abre el chat con el código ya escrito):\n{enlace}"
    return (
        texto + "Pasale el código: tiene que mandárselo a {NOMBRE} por WhatsApp.\n"
        "_Para tener un link, configurá WA_NUMERO_BOT._"
    )


def listar(db: Session, ahora: datetime) -> str:
    lista = vigentes(db, ahora)
    en_curso = db.scalar(select(func.count(Solicitud.id)).where(Solicitud.estado == usuarios.PENDIENTE)) or 0
    sin_terminar = f"\n\n⏳ Altas sin terminar: {en_curso}" if en_curso else ""
    if not lista:
        return "No hay invitaciones vigentes. Mandá *invitar* para crear una." + sin_terminar
    filas = "\n".join(f"      › {i.codigo} · vence el {_dia(i.vence)}" for i in lista)
    return (
        f"🎟️ *INVITACIONES VIGENTES* ({len(lista)})\n\n{filas}{sin_terminar}\n\n"
        f"_Para anular una: *anular {PREFIJO}-XXXX-XXXX*_"
    )


def anular(db: Session, texto: str, actor: int, ahora: datetime) -> str:
    codigo = buscar_codigo(texto)
    if codigo is None:
        return f"No entendí el código. Escribilo así: *anular {PREFIJO}-XXXX-XXXX*"
    invitacion = db.scalar(select(Invitacion).where(Invitacion.codigo == codigo))
    if invitacion is None:
        return f"No encontré el código {codigo}."
    if invitacion.usada:
        return f"El código {codigo} ya se usó: no se puede anular."
    if invitacion.anulada:
        return f"El código {codigo} ya estaba anulado."
    if en_utc(invitacion.vence) <= ahora:
        return f"El código {codigo} ya venció."
    invitacion.anulada = ahora
    db.flush()
    auditoria.registrar(db, auditoria.ANULAR, actor=actor, invitacion=invitacion.id)
    return f"🚫 Listo, anulé {codigo}: ya no sirve."
