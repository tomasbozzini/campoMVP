"""Modo prueba del administrador: sus mensajes, para armar el set de evaluación.

Solo agrega la columna `usuarios.modo_prueba` (falso para todos) y la tabla `pruebas`. No
cambia ni borra datos.

Revisión: 0013
Anterior: 0012
Fecha: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("modo_prueba", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "pruebas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", name="pruebas_usuario_id_fkey"), nullable=False
        ),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("audio", sa.Boolean(), nullable=False),
        sa.Column("historial", sa.JSON(), nullable=False),
        sa.Column("pregunta", sa.String(length=20), nullable=True),
        sa.Column("hoy", sa.Date(), nullable=False),
        sa.Column("interpretacion", sa.JSON(), nullable=False),
        sa.Column("respuesta", sa.Text(), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pruebas_usuario_id", "pruebas", ["usuario_id"])


def downgrade() -> None:
    op.drop_index("ix_pruebas_usuario_id", table_name="pruebas")
    op.drop_table("pruebas")
    with op.batch_alter_table("usuarios") as tabla:
        tabla.drop_column("modo_prueba")
