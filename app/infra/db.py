"""Conexión a la base de datos."""

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.infra.config import config


def crear_motor(url: str) -> Engine:
    # hide_parameters: si una consulta falla, el error (y el log) no muestra los valores,
    # que pueden traer el texto de un mensaje o un teléfono.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, hide_parameters=True, connect_args=connect_args)


engine = crear_motor(config.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


# Nombres de los constraints: los mismos que pone Postgres cuando no se los da nadie. Las
# bases de Postgres creadas antes de la convención (por la 0001 o por create_all) ya los
# tienen, así que no hubo que migrar nada; las de SQLite (solo locales) los tienen sin
# nombre, y una migración que toque uno ahí usa batch_alter_table (que recrea la tabla).
# Ojo: Postgres corta los nombres en 63 caracteres y SQLAlchemy los acorta distinto.
# No hay "ck": no hay CHECK constraints (Boolean no los crea).
CONVENCION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCION)
