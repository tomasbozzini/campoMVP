"""Animales identificados (RP o caravana), para seguir a cada toro de un raspaje a otro.

Solo agrega: la tabla `animales` y la columna `eventos.animal_id` (vacía en los registros que
ya existen). No cambia ni borra datos.

Revisión: 0014
Anterior: 0013
Fecha: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "animales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cuenta_id", sa.Integer(), sa.ForeignKey("cuentas.id", name="animales_cuenta_id_fkey"), nullable=False
        ),
        sa.Column(
            "establecimiento_id",
            sa.Integer(),
            sa.ForeignKey("establecimientos.id", name="animales_establecimiento_id_fkey"),
            nullable=True,
        ),
        sa.Column("rp", sa.String(length=40), nullable=True),
        sa.Column("caravana", sa.String(length=40), nullable=True),
        sa.Column("categoria", sa.String(length=40), nullable=True),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_animales_cuenta_id", "animales", ["cuenta_id"])
    op.create_index("ix_animales_establecimiento_id", "animales", ["establecimiento_id"])
    with op.batch_alter_table("eventos") as t:
        t.add_column(sa.Column("animal_id", sa.Integer(), nullable=True))
        t.create_foreign_key("eventos_animal_id_fkey", "animales", ["animal_id"], ["id"])
        t.create_index("ix_eventos_animal_id", ["animal_id"])


def downgrade() -> None:
    with op.batch_alter_table("eventos") as t:
        t.drop_index("ix_eventos_animal_id")
        t.drop_constraint("eventos_animal_id_fkey", type_="foreignkey")
        t.drop_column("animal_id")
    op.drop_index("ix_animales_establecimiento_id", table_name="animales")
    op.drop_index("ix_animales_cuenta_id", table_name="animales")
    op.drop_table("animales")
