"""Conexión a la base de datos."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.infra.config import config

_connect_args = {"check_same_thread": False} if config.database_url.startswith("sqlite") else {}
engine = create_engine(config.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def crear_tablas() -> None:
    from app.infra import modelos  # noqa: F401  (registra los modelos)

    Base.metadata.create_all(engine)
