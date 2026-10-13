"""Alembic: aplica las migraciones sobre la base de DATABASE_URL (o la conexión que se le pase)."""

from alembic import context
from sqlalchemy import Connection

from app.infra import modelos  # noqa: F401  (registra las tablas)
from app.infra.db import Base, engine

metadata = Base.metadata


def _migrar(conexion: Connection) -> None:
    # render_as_batch: SQLite no sabe cambiar columnas; Alembic copia la tabla en su lugar.
    context.configure(connection=conexion, target_metadata=metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


# Quien llama (app/infra/migrar.py o los tests) puede pasar su propia conexión.
conexion = context.config.attributes.get("conexion")
if conexion is not None:
    _migrar(conexion)
else:
    with engine.connect() as nueva:
        _migrar(nueva)
