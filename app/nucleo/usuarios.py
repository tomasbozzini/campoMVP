"""Quién puede usar el bot: dar y sacar acceso.

Los administradores (ADMIN_TELEFONOS) lo hacen por WhatsApp con "autorizar <número>",
"quitar <número>" y "autorizados", o desde la terminal con `python -m app usuarios ...`.
"""

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.modelos import Cuenta, Solicitud, Usuario
from app.nucleo import auditoria
from app.nucleo.cuaderno import Cuaderno

# Solicitudes de alta (ver app/nucleo/alta.py).
PENDIENTE, APROBADA, RECHAZADA = "pendiente", "aprobada", "rechazada"
POR_CODIGO, POR_PEDIDO, POR_ADMIN = "codigo", "pedido", "admin"


def normalizar_telefono(texto: str) -> str | None:
    """Deja el número como lo manda WhatsApp: 549 + característica + número.

    Acepta "+54 9 249 412-3456" o "542494123456" (sin el 9, como lo guarda Meta).
    """
    digitos = re.sub(r"\D", "", texto)
    if digitos.startswith("54") and not digitos.startswith("549") and len(digitos) == 12:
        digitos = "549" + digitos[2:]
    return digitos if 10 <= len(digitos) <= 15 else None


def nuevo(db: Session, telefono: str, nombre: str | None = None, autorizado: bool = False) -> Usuario:
    """Da de alta a una persona con su propia cuenta (hoy, 1 persona = 1 cuenta)."""
    cuenta = Cuenta()
    db.add(cuenta)
    db.flush()
    usuario = Usuario(telefono=telefono, nombre=nombre, autorizado=autorizado, cuenta_id=cuenta.id)
    db.add(usuario)
    db.flush()
    return usuario


def autorizar(db: Session, telefono: str, actor: int | None = None) -> Usuario:
    """Da acceso a ese número. `actor`: el administrador que lo pidió (None: desde la terminal)."""
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    if usuario is None:
        usuario = nuevo(db, telefono)
    elif usuario.autorizado:
        return usuario  # ya tenía acceso: no cambia nada (el chat de la terminal lo pide cada vez)
    usuario.autorizado = True
    db.add(Solicitud(usuario_id=usuario.id, origen=POR_ADMIN, estado=APROBADA, resuelto=datetime.now(UTC)))
    db.flush()
    auditoria.registrar(db, auditoria.AUTORIZAR, actor=actor, sobre=usuario.id)
    return usuario


def quitar(db: Session, telefono: str, actor: int | None = None) -> bool:
    """Saca el acceso. Los registros de la persona se conservan."""
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    if usuario is None or not usuario.autorizado:
        return False
    usuario.autorizado = False
    db.flush()
    auditoria.registrar(db, auditoria.QUITAR, actor=actor, sobre=usuario.id)
    return True


def eliminar(db: Session, usuario: Usuario) -> None:
    """Borra a la persona con todo lo suyo y su cuenta (hoy, 1 persona = 1 cuenta)."""
    Cuaderno(db, usuario).borrar_todo()
    cuenta = db.get(Cuenta, usuario.cuenta_id)
    db.delete(usuario)
    db.flush()
    if cuenta is not None:
        db.delete(cuenta)
        db.flush()


def autorizados(db: Session) -> list[Usuario]:
    return list(db.scalars(select(Usuario).where(Usuario.autorizado.is_(True)).order_by(Usuario.creado)).all())
