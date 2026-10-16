"""Borrados grandes esperando confirmación: qué se va a borrar, registros o pendientes.

Solo agrega la columna `que` a `borrados_pendientes`. Lo que ya estaba esperando son
registros (hasta ahora no había otra cosa): toma "registros". No cambia ni borra datos.

Revisión: 0011
Anterior: 0010
Fecha: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "borrados_pendientes",
        sa.Column("que", sa.String(length=10), nullable=False, server_default="registros"),
    )


def downgrade() -> None:
    with op.batch_alter_table("borrados_pendientes") as tabla:
        tabla.drop_column("que")
