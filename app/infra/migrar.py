"""Deja la base de datos al día con las migraciones de Alembic, sin perder datos.

`preparar_base()` se llama al arrancar el servidor y los comandos de terminal:

- Base vacía: crea todo aplicando las migraciones.
- Base que ya usa Alembic: aplica las migraciones que falten.
- Base creada antes de Alembic (con create_all): si sus tablas coinciden con la
  migración base, la marca como en esa versión ("stamp", no toca los datos) y aplica lo
  que falte. Si no coinciden, no hace nada y avisa qué difiere, para resolverlo a mano.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, inspect

from app.infra import modelos  # noqa: F401  (registra las tablas)
from app.infra.db import Base

log = logging.getLogger(__name__)

CARPETA = Path(__file__).parent / "migraciones"
BASE = "0001"  # la migración que equivale al esquema de antes de Alembic


class EsquemaDistinto(RuntimeError):
    """La base tiene tablas de antes de Alembic que no coinciden con la migración base."""


def _config(conexion: Connection) -> Config:
    config = Config()
    config.set_main_option("script_location", str(CARPETA))
    config.attributes["conexion"] = conexion
    return config


def diferencias(conexion: Connection) -> list[str]:
    """Qué difiere entre las tablas de la base y los modelos del código."""
    contexto = MigrationContext.configure(conexion, opts={"compare_type": True})
    return [str(d) for d in compare_metadata(contexto, Base.metadata)]


def version(conexion: Connection) -> str | None:
    return MigrationContext.configure(conexion).get_current_revision()


def preparar_base(engine: Engine) -> None:
    with engine.begin() as conexion:
        tablas = set(inspect(conexion).get_table_names())
        config = _config(conexion)
        if "alembic_version" not in tablas and tablas & set(Base.metadata.tables):
            difieren = diferencias(conexion)
            if difieren:
                raise EsquemaDistinto(
                    "La base tiene tablas de antes de Alembic que no coinciden con el código:\n  "
                    + "\n  ".join(difieren)
                    + "\nNo se tocó nada. Hacé una copia de la base y revisá estas diferencias."
                )
            log.warning("Base existente sin Alembic: se marca como versión %s, sin tocar los datos", BASE)
            command.stamp(config, BASE)
        command.upgrade(config, "head")
