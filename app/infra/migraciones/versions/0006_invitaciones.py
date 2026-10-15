"""Alta por código de invitación: invitaciones, solicitudes de alta e intentos fallidos.

Revisión: 0006
Anterior: 0005
Fecha: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invitaciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("codigo", sa.String(length=20), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vence", sa.DateTime(timezone=True), nullable=False),
        sa.Column("creada_por", sa.Integer(), nullable=True),
        sa.Column("usada", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anulada", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("codigo", name="invitaciones_codigo_key"),
    )
    op.create_table(
        "solicitudes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", name="solicitudes_usuario_id_fkey"), nullable=False
        ),
        sa.Column(
            "invitacion_id",
            sa.Integer(),
            sa.ForeignKey("invitaciones.id", name="solicitudes_invitacion_id_fkey"),
            nullable=True,
        ),
        sa.Column("origen", sa.String(length=10), nullable=False),
        sa.Column("estado", sa.String(length=10), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resuelto", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_solicitudes_usuario_id", "solicitudes", ["usuario_id"])
    op.create_index("ix_solicitudes_estado", "solicitudes", ["estado"])
    op.create_table(
        "intentos_alta",
        sa.Column("telefono_hash", sa.String(length=64), primary_key=True),
        sa.Column("desde", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("intentos_alta")
    op.drop_index("ix_solicitudes_estado", table_name="solicitudes")
    op.drop_index("ix_solicitudes_usuario_id", table_name="solicitudes")
    op.drop_table("solicitudes")
    op.drop_table("invitaciones")
