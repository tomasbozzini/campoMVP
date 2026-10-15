"""Nombres de los establecimientos, prolijos como la localidad.

"estancia LA PASTORA" pasa a "Estancia la Pastora": mayúscula inicial, las partículas (de,
la, el...) en minúscula salvo al principio, y sin espacios de más. Solo cambian mayúsculas
y espacios; la clave con la que se reconoce cada establecimiento no cambia.

No tiene vuelta atrás para cómo estaban escritos: la vuelta atrás no hace nada.

La regla se copia acá, sin importar el código, para que la migración haga siempre lo mismo.

Revisión: 0008
Anterior: 0007
Fecha: 2026-10-15
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_establecimientos = sa.table("establecimientos", sa.column("id", sa.Integer()), sa.column("nombre", sa.String()))

_PARTICULAS = {"de", "del", "la", "las", "los", "el", "y", "e", "da", "di", "van", "von"}
_INICIAL = re.compile(r"(^|[-'])(\w)")


def _prolijo(texto: str) -> str:
    """Como app/infra/texto.py al escribir esto."""
    palabras = texto.lower().split()
    return " ".join(
        p if i > 0 and p in _PARTICULAS else _INICIAL.sub(lambda m: m.group(1) + m.group(2).upper(), p)
        for i, p in enumerate(palabras)
    )


def upgrade() -> None:
    conexion = op.get_bind()
    for campo_id, nombre in conexion.execute(sa.select(_establecimientos.c.id, _establecimientos.c.nombre)).all():
        if (limpio := _prolijo(nombre)) != nombre:
            conexion.execute(
                sa.update(_establecimientos).where(_establecimientos.c.id == campo_id).values(nombre=limpio)
            )


def downgrade() -> None:
    pass
