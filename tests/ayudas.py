"""Datos de prueba que comparten varios tests."""

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.infra.modelos import Usuario
from app.nucleo import usuarios


def con_perfil(db: Session, telefono: str, rubro: str = "productor") -> Usuario:
    """Un usuario habilitado que ya respondió las preguntas del alta."""
    usuario = usuarios.autorizar(db, telefono)
    usuario.nombre_completo, usuario.rubro, usuario.localidad = "Juana Gómez", rubro, "Tandil"
    db.flush()
    return usuario


def con_perfil_en(motor: Engine, telefono: str, rubro: str = "productor") -> None:
    """Lo mismo, guardado en la base del servidor de prueba (para los tests por el webhook)."""
    with sessionmaker(bind=motor)() as db:
        con_perfil(db, telefono, rubro)
        db.commit()
