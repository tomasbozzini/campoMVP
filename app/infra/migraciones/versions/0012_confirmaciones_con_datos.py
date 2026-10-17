"""Confirmaciones con datos: además de los ids, lo que hace falta para terminar el pedido.

Solo agrega la columna `datos` (JSON, opcional) a `borrados_pendientes`, que pasa a guardar
cualquier pregunta que espera un *sí*: un borrado grande, una corrección de muchos pendientes
(los cambios) o un campo parecido a otro (el pedido entero). No cambia ni borra datos.

Revisión: 0012
Anterior: 0011
Fecha: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("borrados_pendientes", sa.Column("datos", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("borrados_pendientes") as tabla:
        tabla.drop_column("datos")
