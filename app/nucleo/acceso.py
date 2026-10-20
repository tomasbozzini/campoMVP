"""Quién puede usar el bot. A los números sin acceso no se les gasta IA ni se los guarda."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.config import config
from app.infra.marca import NOMBRE
from app.infra.modelos import Usuario
from app.nucleo import usuarios
from app.nucleo.cuaderno import Cuaderno

# Para quien escribe sin acceso y sin código de invitación (no se guarda nada).
NO_AUTORIZADO = f"""👋 *¡Hola! Soy {NOMBRE}.*

Estoy en prueba privada: por ahora solo pueden usarme las personas invitadas.
Si te pasaron un código de invitación, mandámelo por acá."""


def es_admin(telefono: str) -> bool:
    return telefono in config.admin_telefonos


def puede_usar_ia(db: Session, telefono: str) -> bool:
    """Para los audios: no transcribimos nada de números sin acceso."""
    if es_admin(telefono):
        return True
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    return usuario is not None and usuario.autorizado


def rubro(db: Session, telefono: str) -> str | None:
    """El rubro de ese número (para el glosario de los audios); None si no tiene."""
    return db.scalar(select(Usuario.rubro).where(Usuario.telefono == telefono))


def nombres_propios(db: Session, telefono: str) -> list[str]:
    """Los nombres de los campos y lotes de ese número, para el glosario de los audios."""
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    return Cuaderno(db, usuario).nombres_propios() if usuario is not None else []


def usuario_con_acceso(db: Session, telefono: str, nombre: str | None) -> Usuario | None:
    """El usuario si tiene acceso; None si no. Los administradores se dan de alta solos."""
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    if usuario is None and es_admin(telefono):
        usuario = usuarios.nuevo(db, telefono, nombre, autorizado=True)
    if usuario is None or not (usuario.autorizado or es_admin(telefono)):
        return None
    if nombre and not usuario.nombre:
        usuario.nombre = nombre
    return usuario
