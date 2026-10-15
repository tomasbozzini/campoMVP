"""Perfil: nombre y apellido, rubro, localidad y matrícula de cada usuario.

Los usuarios que ya existen quedan con estos datos vacíos: la próxima vez que escriban se
les hacen las preguntas fijas del alta (app/nucleo/perfil.py). `pregunta` guarda cuál
espera respuesta.

Revisión: 0004
Anterior: 0003
Fecha: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNAS = [
    ("nombre_completo", 80),
    ("rubro", 20),
    ("localidad", 80),
    ("matricula", 30),
    ("pregunta", 20),
]


def upgrade() -> None:
    with op.batch_alter_table("usuarios") as t:
        for nombre, largo in COLUMNAS:
            t.add_column(sa.Column(nombre, sa.String(length=largo), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("usuarios") as t:
        for nombre, _ in reversed(COLUMNAS):
            t.drop_column(nombre)
