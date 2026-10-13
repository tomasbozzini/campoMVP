"""Quién puede usar el bot. A los números sin acceso no se les gasta IA ni se los guarda."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.config import config
from app.infra.modelos import Usuario

NO_AUTORIZADO = """👋 *¡Hola!*

Este número todavía no tiene acceso al asistente.
Pedile al administrador que te habilite."""


def es_admin(telefono: str) -> bool:
    return telefono in config.admin_telefonos


def puede_usar_ia(db: Session, telefono: str) -> bool:
    """Para los audios: no transcribimos nada de números sin acceso."""
    if es_admin(telefono):
        return True
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    return usuario is not None and usuario.autorizado


def usuario_con_acceso(db: Session, telefono: str, nombre: str | None) -> Usuario | None:
    """El usuario si tiene acceso; None si no. Los administradores se dan de alta solos."""
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    if usuario is None and es_admin(telefono):
        usuario = Usuario(telefono=telefono, nombre=nombre, autorizado=True)
        db.add(usuario)
        db.flush()
    if usuario is None or not (usuario.autorizado or es_admin(telefono)):
        return None
    if nombre and not usuario.nombre:
        usuario.nombre = nombre
    return usuario
