"""Conexión a la base de datos."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.infra.config import config

_connect_args = {"check_same_thread": False} if config.database_url.startswith("sqlite") else {}
engine = create_engine(config.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def preparar_base() -> None:
    """Crea la base o la pone al día con las migraciones (ver app/infra/migrar.py)."""
    from app.infra.migrar import preparar_base as preparar

    preparar(engine)
