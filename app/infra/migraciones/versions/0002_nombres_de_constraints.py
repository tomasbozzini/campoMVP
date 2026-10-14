"""Nombres de los constraints según la convención (app/infra/db.py).

La convención es la que usa Postgres por defecto, así que en Postgres no hay nada que hacer:
sus bases ya tienen esos nombres. SQLite, en cambio, guarda sin nombre las claves primarias,
foráneas y únicas que se crearon sin nombre: acá se recrean sus tablas (modo batch de
Alembic, que copia los datos) con los nombres de la convención.

Revisión: 0002
Anterior: 0001
Fecha: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

from app.infra.db import CONVENCION

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Primero la tabla a la que apuntan las demás.
TABLAS = [
    "usuarios",
    "eventos",
    "mensajes_procesados",
    "cotizaciones",
    "uso_diario",
    "productos_veterinarios",
    "mensajes_chat",
    "borrados_pendientes",
]


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for tabla in TABLAS:
        with op.batch_alter_table(tabla, recreate="always", naming_convention=CONVENCION):
            pass


def downgrade() -> None:
    # Los nombres no cambian cómo funciona nada: no hace falta sacarlos.
    pass
