"""Quién puede usar el bot: dar y sacar acceso.

Los administradores (ADMIN_TELEFONOS) lo hacen por WhatsApp con "autorizar <número>",
"quitar <número>" y "autorizados", o desde la terminal con `python -m app usuarios ...`.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.modelos import Usuario


def normalizar_telefono(texto: str) -> str | None:
    """Deja el número como lo manda WhatsApp: 549 + característica + número.

    Acepta "+54 9 249 412-3456" o "542494123456" (sin el 9, como lo guarda Meta).
    """
    digitos = re.sub(r"\D", "", texto)
    if digitos.startswith("54") and not digitos.startswith("549") and len(digitos) == 12:
        digitos = "549" + digitos[2:]
    return digitos if 10 <= len(digitos) <= 15 else None


def autorizar(db: Session, telefono: str) -> Usuario:
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    if usuario is None:
        usuario = Usuario(telefono=telefono)
        db.add(usuario)
    usuario.autorizado = True
    db.flush()
    return usuario


def quitar(db: Session, telefono: str) -> bool:
    """Saca el acceso. Los registros de la persona se conservan."""
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    if usuario is None or not usuario.autorizado:
        return False
    usuario.autorizado = False
    db.flush()
    return True


def autorizados(db: Session) -> list[Usuario]:
    return list(db.scalars(select(Usuario).where(Usuario.autorizado.is_(True)).order_by(Usuario.creado)).all())
