"""Conexión a la base de datos."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.infra.config import config


def crear_motor(url: str) -> Engine:
    # hide_parameters: si una consulta falla, el error (y el log) no muestra los valores,
    # que pueden traer el texto de un mensaje o un teléfono.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, hide_parameters=True, connect_args=connect_args)


engine = crear_motor(config.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass
