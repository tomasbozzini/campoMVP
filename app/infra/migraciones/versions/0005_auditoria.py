"""Auditoría de acciones sensibles: solo ids numéricos y cantidades.

Revisión: 0005
Anterior: 0004
Fecha: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auditoria",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accion", sa.String(length=30), nullable=False),
        sa.Column("actor", sa.Integer(), nullable=True),
        sa.Column("sobre", sa.Integer(), nullable=True),
        sa.Column("detalle", sa.JSON(), nullable=True),
    )
    op.create_index("ix_auditoria_fecha", "auditoria", ["fecha"])


def downgrade() -> None:
    op.drop_index("ix_auditoria_fecha", table_name="auditoria")
    op.drop_table("auditoria")
