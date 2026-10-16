"""Pendientes: lo que la persona tiene que hacer más adelante.

Solo agrega la tabla `pendientes`. No cambia ni borra datos.

Revisión: 0010
Anterior: 0009
Fecha: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pendientes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cuenta_id", sa.Integer(), sa.ForeignKey("cuentas.id", name="pendientes_cuenta_id_fkey"), nullable=False
        ),
        sa.Column(
            "usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", name="pendientes_usuario_id_fkey"), nullable=False
        ),
        sa.Column(
            "establecimiento_id",
            sa.Integer(),
            sa.ForeignKey("establecimientos.id", name="pendientes_establecimiento_id_fkey"),
            nullable=True,
        ),
        sa.Column("lote_id", sa.Integer(), sa.ForeignKey("lotes.id", name="pendientes_lote_id_fkey"), nullable=True),
        sa.Column("texto", sa.String(length=200), nullable=False),
        sa.Column("vence", sa.Date(), nullable=True),
        sa.Column("hecho", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pendientes_cuenta_id", "pendientes", ["cuenta_id"])
    op.create_index("ix_pendientes_usuario_id", "pendientes", ["usuario_id"])
    op.create_index("ix_pendientes_hecho", "pendientes", ["hecho"])


def downgrade() -> None:
    op.drop_index("ix_pendientes_hecho", table_name="pendientes")
    op.drop_index("ix_pendientes_usuario_id", table_name="pendientes")
    op.drop_index("ix_pendientes_cuenta_id", table_name="pendientes")
    op.drop_table("pendientes")
