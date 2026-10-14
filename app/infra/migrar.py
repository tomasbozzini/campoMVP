"""Deja la base de datos al día con las migraciones de Alembic, sin perder datos.

Solo migra `python -m app db migrar` (el Dockerfile lo corre antes de arrancar el bot). El
servidor y los demás comandos llaman a `revisar()`: si la base no está al día, avisan y no
arrancan, en vez de cambiarla de costado.

`preparar_base()`:

- Base vacía: crea todo aplicando las migraciones.
- Base que ya usa Alembic: aplica las migraciones que falten.
- Base creada antes de Alembic (con create_all): se compara con el esquema de la migración
  base (0001), que es la versión que tiene, y no con los modelos actuales, que pueden ir
  varias migraciones más adelante. Si coincide, se marca como en la 0001 ("stamp", no toca
  los datos) y se aplican las migraciones siguientes. Si solo le faltan tablas enteras
  (las de funciones que se sumaron después), se crean y sigue igual. Si difiere en otra
  cosa, no se toca nada y se avisa qué difiere, para resolverlo a mano.
"""

import logging
from pathlib import Path
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, MetaData, inspect

from app.infra import modelos  # noqa: F401  (registra las tablas)
from app.infra.db import Base

log = logging.getLogger(__name__)

CARPETA = Path(__file__).parent / "migraciones"
BASE = "0001"  # la migración que equivale al esquema de antes de Alembic


class EsquemaDistinto(RuntimeError):
    """La base tiene tablas de antes de Alembic que no coinciden con la migración base."""


class FaltaMigrar(RuntimeError):
    """La base no está en la última migración del código."""


def _config(conexion: Connection) -> Config:
    config = Config()
    config.set_main_option("script_location", str(CARPETA))
    config.attributes["conexion"] = conexion
    return config


def esquema_base() -> MetaData:
    """Las tablas tal como las crea la migración base."""
    esquema: MetaData = ScriptDirectory(str(CARPETA)).get_revision(BASE).module.esquema
    return esquema


def _comparar(conexion: Connection, esquema: MetaData) -> list[Any]:
    contexto = MigrationContext.configure(conexion, opts={"compare_type": True})
    # Los cambios de una columna vienen agrupados en una lista; el resto, de a uno.
    return [d for grupo in compare_metadata(contexto, esquema) for d in (grupo if isinstance(grupo, list) else [grupo])]


def _describir(d: tuple[Any, ...]) -> str:
    """Una diferencia de Alembic en castellano: qué tiene la base contra lo que se esperaba."""
    tipo = d[0]
    if tipo in ("add_table", "remove_table"):
        return f"{'falta la tabla' if tipo == 'add_table' else 'tabla de más'} {d[1].name}"
    if tipo in ("add_column", "remove_column"):
        return f"{'falta la columna' if tipo == 'add_column' else 'columna de más'} {d[2]}.{d[3].name}"
    if tipo in ("add_index", "remove_index"):
        return f"{'falta el índice' if tipo == 'add_index' else 'índice de más'} {d[1].name} en {d[1].table.name}"
    if tipo in ("add_constraint", "remove_constraint", "add_fk", "remove_fk"):
        columnas = ", ".join(c.name for c in d[1].columns)
        return f"{'falta' if tipo.startswith('add') else 'sobra'} la restricción de {d[1].table.name} ({columnas})"
    if tipo == "modify_type":
        return f"la columna {d[2]}.{d[3]} es {d[5]} y se esperaba {d[6]}"
    if tipo == "modify_nullable":
        esperado = "acepte vacíos" if d[6] else "no acepte vacíos"
        return f"la columna {d[2]}.{d[3]} tendría que ser una que {esperado}"
    return str(d)


def diferencias(conexion: Connection) -> list[str]:
    """Qué difiere entre las tablas de la base y los modelos del código."""
    return [_describir(d) for d in _comparar(conexion, Base.metadata)]


def version(conexion: Connection) -> str | None:
    return MigrationContext.configure(conexion).get_current_revision()


def _adoptar(conexion: Connection, config: Config) -> None:
    """Marca una base de antes de Alembic como en la versión base, si coincide con ella."""
    esquema = esquema_base()
    difieren = _comparar(conexion, esquema)
    faltan = {d[1].name for d in difieren if d[0] == "add_table"}
    # Los índices de una tabla que falta se crean con ella.
    resto = [d for d in difieren if d[0] != "add_table" and not (d[0] == "add_index" and d[1].table.name in faltan)]
    if resto:
        raise EsquemaDistinto(
            f"La base tiene tablas de antes de Alembic que no coinciden con la versión {BASE}:\n  - "
            + "\n  - ".join(_describir(d) for d in resto)
            + "\nNo se tocó nada. Hacé una copia de la base y revisá estas diferencias."
        )
    if faltan:
        log.warning("Base existente sin Alembic: se crean las tablas que le faltaban (%s)", ", ".join(sorted(faltan)))
        esquema.create_all(conexion, tables=[esquema.tables[nombre] for nombre in sorted(faltan)])
    log.warning("Base existente sin Alembic: se marca como versión %s, sin tocar los datos", BASE)
    command.stamp(config, BASE)


def preparar_base(engine: Engine) -> None:
    with engine.begin() as conexion:
        tablas = set(inspect(conexion).get_table_names())
        config = _config(conexion)
        if "alembic_version" not in tablas and tablas & set(esquema_base().tables):
            _adoptar(conexion, config)
        command.upgrade(config, "head")


def revisar(engine: Engine) -> None:
    """Falla con FaltaMigrar si la base no está en la última migración. No cambia nada."""
    with engine.connect() as conexion:
        actual = version(conexion)
    ultima = ScriptDirectory(str(CARPETA)).get_current_head()
    if actual != ultima:
        estado = f"está en la versión {actual}" if actual else "no está creada o es de antes de Alembic"
        raise FaltaMigrar(
            f"La base de datos {estado} y el código necesita la {ultima}. Ponela al día con: python -m app db migrar"
        )
