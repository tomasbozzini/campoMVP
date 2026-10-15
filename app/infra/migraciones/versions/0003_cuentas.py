"""Cuentas: los registros pasan a ser de una cuenta (hoy, 1 persona = 1 cuenta).

Cada usuario que ya existe recibe su propia cuenta, y sus registros pasan a esa cuenta.
`eventos.usuario_id` queda como quién anotó cada registro.

Las tablas se describen acá, sin importar los modelos, para que la migración haga siempre
lo mismo aunque los modelos cambien después.

Revisión: 0003
Anterior: 0002
Fecha: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_cuentas = sa.table("cuentas", sa.column("id", sa.Integer()), sa.column("creado", sa.DateTime(timezone=True)))
_usuarios = sa.table(
    "usuarios",
    sa.column("id", sa.Integer()),
    sa.column("creado", sa.DateTime(timezone=True)),
    sa.column("cuenta_id", sa.Integer()),
)
_eventos = sa.table("eventos", sa.column("usuario_id", sa.Integer()), sa.column("cuenta_id", sa.Integer()))


def upgrade() -> None:
    op.create_table(
        "cuentas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
    )
    for tabla in ("usuarios", "eventos"):
        with op.batch_alter_table(tabla) as t:
            t.add_column(sa.Column("cuenta_id", sa.Integer(), nullable=True))

    # Una cuenta por usuario, de a uno: así cada base (SQLite o Postgres) numera las cuentas
    # con su propia secuencia y las altas siguientes no chocan.
    conexion = op.get_bind()
    for usuario_id, creado in conexion.execute(sa.select(_usuarios.c.id, _usuarios.c.creado)).all():
        cuenta_id = conexion.execute(sa.insert(_cuentas).values(creado=creado).returning(_cuentas.c.id)).scalar_one()
        conexion.execute(sa.update(_usuarios).where(_usuarios.c.id == usuario_id).values(cuenta_id=cuenta_id))
        conexion.execute(sa.update(_eventos).where(_eventos.c.usuario_id == usuario_id).values(cuenta_id=cuenta_id))
    huerfanos = conexion.execute(
        sa.select(sa.func.count()).select_from(_eventos).where(_eventos.c.cuenta_id.is_(None))
    ).scalar_one()
    if huerfanos:
        raise RuntimeError(
            f"Hay {huerfanos} registros de usuarios que ya no existen: no se puede saber de qué cuenta son. "
            "No se cambió nada; revisalos a mano antes de migrar."
        )

    for tabla in ("usuarios", "eventos"):
        with op.batch_alter_table(tabla) as t:
            t.alter_column("cuenta_id", existing_type=sa.Integer(), nullable=False)
            t.create_foreign_key(f"{tabla}_cuenta_id_fkey", "cuentas", ["cuenta_id"], ["id"])
            t.create_index(f"ix_{tabla}_cuenta_id", ["cuenta_id"])


def downgrade() -> None:
    for tabla in ("eventos", "usuarios"):
        with op.batch_alter_table(tabla) as t:
            t.drop_index(f"ix_{tabla}_cuenta_id")
            t.drop_constraint(f"{tabla}_cuenta_id_fkey", type_="foreignkey")
            t.drop_column("cuenta_id")
    op.drop_table("cuentas")
