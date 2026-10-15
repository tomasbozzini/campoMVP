"""Sesiones de trabajo: la tabla y la sesión de cada registro.

Solo agrega: la tabla `sesiones` y la columna `eventos.sesion_id` (vacía en los registros
que ya existen). No cambia ni borra datos.

Revisión: 0009
Anterior: 0008
Fecha: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sesiones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cuenta_id", sa.Integer(), sa.ForeignKey("cuentas.id", name="sesiones_cuenta_id_fkey"), nullable=False
        ),
        sa.Column(
            "usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", name="sesiones_usuario_id_fkey"), nullable=False
        ),
        sa.Column(
            "establecimiento_id",
            sa.Integer(),
            sa.ForeignKey("establecimientos.id", name="sesiones_establecimiento_id_fkey"),
            nullable=True,
        ),
        sa.Column("lote_id", sa.Integer(), sa.ForeignKey("lotes.id", name="sesiones_lote_id_fkey"), nullable=True),
        sa.Column("actividad", sa.String(length=60), nullable=True),
        sa.Column("abierta", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultima_actividad", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cerrada", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_cierre", sa.String(length=10), nullable=True),
    )
    op.create_index("ix_sesiones_cuenta_id", "sesiones", ["cuenta_id"])
    op.create_index("ix_sesiones_usuario_id", "sesiones", ["usuario_id"])
    op.create_index("ix_sesiones_cerrada", "sesiones", ["cerrada"])
    with op.batch_alter_table("eventos") as t:
        t.add_column(sa.Column("sesion_id", sa.Integer(), nullable=True))
        t.create_foreign_key("eventos_sesion_id_fkey", "sesiones", ["sesion_id"], ["id"])
        t.create_index("ix_eventos_sesion_id", ["sesion_id"])


def downgrade() -> None:
    with op.batch_alter_table("eventos") as t:
        t.drop_index("ix_eventos_sesion_id")
        t.drop_constraint("eventos_sesion_id_fkey", type_="foreignkey")
        t.drop_column("sesion_id")
    op.drop_index("ix_sesiones_cerrada", table_name="sesiones")
    op.drop_index("ix_sesiones_usuario_id", table_name="sesiones")
    op.drop_index("ix_sesiones_cuenta_id", table_name="sesiones")
    op.drop_table("sesiones")
