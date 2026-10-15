"""Establecimientos y lotes como tablas.

Hasta acá cada registro guardaba su establecimiento y sus lotes como texto. Pasan a ser
tablas de la cuenta y los registros apuntan a ellas:

- Un establecimiento por cuenta y clave (la que ya tenían los registros: "Estancia La
  Esperanza" y "la esperanza" son uno solo). Su nombre es el del primer registro que lo
  nombró. La misma estancia en dos cuentas son dos establecimientos: cada uno ve lo suyo.
- Un lote por cuenta, establecimiento y nombre. El destino de un traslado es un lote del
  mismo establecimiento que el registro. Un lote de un registro sin establecimiento queda
  suelto.
- El establecimiento actual de cada usuario apunta al suyo (se crea si ningún registro lo
  nombraba).

Después se borran las columnas de texto. Las tablas y cómo se normalizan los nombres se
describen acá, sin importar el código, para que la migración haga siempre lo mismo aunque
el código cambie después.

Revisión: 0007
Anterior: 0006
Fecha: 2026-10-15
"""

import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_establecimientos = sa.table(
    "establecimientos",
    sa.column("id", sa.Integer()),
    sa.column("cuenta_id", sa.Integer()),
    sa.column("nombre", sa.String()),
    sa.column("clave", sa.String()),
    sa.column("creado", sa.DateTime(timezone=True)),
)
_lotes = sa.table(
    "lotes",
    sa.column("id", sa.Integer()),
    sa.column("cuenta_id", sa.Integer()),
    sa.column("establecimiento_id", sa.Integer()),
    sa.column("nombre", sa.String()),
    sa.column("creado", sa.DateTime(timezone=True)),
)
_eventos = sa.table(
    "eventos",
    sa.column("id", sa.Integer()),
    sa.column("cuenta_id", sa.Integer()),
    sa.column("establecimiento", sa.String()),
    sa.column("establecimiento_clave", sa.String()),
    sa.column("lote", sa.String()),
    sa.column("lote_destino", sa.String()),
    sa.column("establecimiento_id", sa.Integer()),
    sa.column("lote_id", sa.Integer()),
    sa.column("lote_destino_id", sa.Integer()),
)
_usuarios = sa.table(
    "usuarios",
    sa.column("id", sa.Integer()),
    sa.column("cuenta_id", sa.Integer()),
    sa.column("establecimiento_actual", sa.String()),
    sa.column("establecimiento_actual_id", sa.Integer()),
)

# Columnas nuevas de los registros: (columna, tabla a la que apunta).
_REFERENCIAS = [("establecimiento_id", "establecimientos"), ("lote_id", "lotes"), ("lote_destino_id", "lotes")]


def _clave(nombre: str | None) -> str | None:
    """ "Estancia La Esperanza" -> "la esperanza" (como app/nucleo/normalizar.py al escribir esto)."""
    if not nombre:
        return None
    texto = "".join(c for c in unicodedata.normalize("NFKD", nombre.strip().lower()) if not unicodedata.combining(c))
    for prefijo in ("estancia ", "establecimiento ", "campo ", "el campo "):
        if texto.startswith(prefijo):
            texto = texto[len(prefijo) :]
    return " ".join(texto.split()) or None


def _lote(nombre: str | None) -> str | None:
    """ "Lote 3" -> "3", "Potrero Grande" -> "potrero grande"."""
    if not nombre:
        return None
    texto = str(nombre).strip().lower()
    for prefijo in ("el lote ", "lote ", "lote n°", "lote nro "):
        if texto.startswith(prefijo):
            texto = texto[len(prefijo) :].strip()
    return texto[:60] or None


class _Creador:
    """Crea cada establecimiento y lote una sola vez, de a uno: así cada base (SQLite o
    Postgres) los numera con su propia secuencia y las altas siguientes no chocan."""

    def __init__(self, conexion: sa.Connection) -> None:
        self.conexion = conexion
        self.ahora = datetime.now(UTC)
        self.campos: dict[tuple[int, str], int] = {}
        self.lotes: dict[tuple[int, int | None, str], int] = {}

    def campo(self, cuenta_id: int, nombre: str | None, clave: str | None) -> int | None:
        clave = clave or _clave(nombre)
        if not clave:
            return None
        if (cuenta_id, clave) not in self.campos:
            valores = {
                "cuenta_id": cuenta_id,
                "nombre": " ".join((nombre or clave).split())[:120],
                "clave": clave[:120],
                "creado": self.ahora,
            }
            self.campos[(cuenta_id, clave)] = self.conexion.execute(
                sa.insert(_establecimientos).values(valores).returning(_establecimientos.c.id)
            ).scalar_one()
        return self.campos[(cuenta_id, clave)]

    def lote(self, cuenta_id: int, campo_id: int | None, nombre: str | None) -> int | None:
        limpio = _lote(nombre)
        if not limpio:
            return None
        if (cuenta_id, campo_id, limpio) not in self.lotes:
            valores = {"cuenta_id": cuenta_id, "establecimiento_id": campo_id, "nombre": limpio, "creado": self.ahora}
            self.lotes[(cuenta_id, campo_id, limpio)] = self.conexion.execute(
                sa.insert(_lotes).values(valores).returning(_lotes.c.id)
            ).scalar_one()
        return self.lotes[(cuenta_id, campo_id, limpio)]


def upgrade() -> None:
    op.create_table(
        "establecimientos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cuenta_id",
            sa.Integer(),
            sa.ForeignKey("cuentas.id", name="establecimientos_cuenta_id_fkey"),
            nullable=False,
        ),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("clave", sa.String(length=120), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cuenta_id", "clave", name="establecimientos_cuenta_id_clave_key"),
    )
    op.create_index("ix_establecimientos_cuenta_id", "establecimientos", ["cuenta_id"])
    op.create_table(
        "lotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cuenta_id", sa.Integer(), sa.ForeignKey("cuentas.id", name="lotes_cuenta_id_fkey"), nullable=False),
        sa.Column(
            "establecimiento_id",
            sa.Integer(),
            sa.ForeignKey("establecimientos.id", name="lotes_establecimiento_id_fkey"),
            nullable=True,
        ),
        sa.Column("nombre", sa.String(length=60), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "cuenta_id", "establecimiento_id", "nombre", name="lotes_cuenta_id_establecimiento_id_nombre_key"
        ),
    )
    op.create_index("ix_lotes_cuenta_id", "lotes", ["cuenta_id"])
    op.create_index("ix_lotes_establecimiento_id", "lotes", ["establecimiento_id"])

    with op.batch_alter_table("eventos") as t:
        for columna, tabla in _REFERENCIAS:
            t.add_column(sa.Column(columna, sa.Integer(), nullable=True))
            t.create_foreign_key(f"eventos_{columna}_fkey", tabla, [columna], ["id"])
            t.create_index(f"ix_eventos_{columna}", [columna])
    with op.batch_alter_table("usuarios") as t:
        t.add_column(sa.Column("establecimiento_actual_id", sa.Integer(), nullable=True))
        t.create_foreign_key(
            "usuarios_establecimiento_actual_id_fkey", "establecimientos", ["establecimiento_actual_id"], ["id"]
        )

    conexion = op.get_bind()
    crear = _Creador(conexion)
    eventos = conexion.execute(
        sa.select(
            _eventos.c.id,
            _eventos.c.cuenta_id,
            _eventos.c.establecimiento,
            _eventos.c.establecimiento_clave,
            _eventos.c.lote,
            _eventos.c.lote_destino,
        ).order_by(_eventos.c.id)  # el nombre de cada establecimiento es el del primer registro
    ).all()
    for evento_id, cuenta_id, nombre, clave, lote, destino in eventos:
        if not (nombre or clave or lote or destino):
            continue
        campo_id = crear.campo(cuenta_id, nombre, clave)
        conexion.execute(
            sa.update(_eventos)
            .where(_eventos.c.id == evento_id)
            .values(
                establecimiento_id=campo_id,
                lote_id=crear.lote(cuenta_id, campo_id, lote),
                lote_destino_id=crear.lote(cuenta_id, campo_id, destino),
            )
        )
    usuarios = conexion.execute(
        sa.select(_usuarios.c.id, _usuarios.c.cuenta_id, _usuarios.c.establecimiento_actual).where(
            _usuarios.c.establecimiento_actual.is_not(None)
        )
    ).all()
    for usuario_id, cuenta_id, actual in usuarios:
        conexion.execute(
            sa.update(_usuarios)
            .where(_usuarios.c.id == usuario_id)
            .values(establecimiento_actual_id=crear.campo(cuenta_id, actual, None))
        )

    with op.batch_alter_table("eventos") as t:
        t.drop_index("ix_eventos_establecimiento_clave")
        t.drop_index("ix_eventos_lote")
        for columna in ("establecimiento", "establecimiento_clave", "lote", "lote_destino"):
            t.drop_column(columna)
    with op.batch_alter_table("usuarios") as t:
        t.drop_column("establecimiento_actual")


def downgrade() -> None:
    with op.batch_alter_table("eventos") as t:
        t.add_column(sa.Column("establecimiento", sa.String(length=120), nullable=True))
        t.add_column(sa.Column("establecimiento_clave", sa.String(length=120), nullable=True))
        t.add_column(sa.Column("lote", sa.String(length=60), nullable=True))
        t.add_column(sa.Column("lote_destino", sa.String(length=60), nullable=True))
        t.create_index("ix_eventos_establecimiento_clave", ["establecimiento_clave"])
        t.create_index("ix_eventos_lote", ["lote"])
    with op.batch_alter_table("usuarios") as t:
        t.add_column(sa.Column("establecimiento_actual", sa.String(length=120), nullable=True))

    conexion = op.get_bind()
    campos = {
        i: (n, c)
        for i, n, c in conexion.execute(
            sa.select(_establecimientos.c.id, _establecimientos.c.nombre, _establecimientos.c.clave)
        )
    }
    lotes = dict(conexion.execute(sa.select(_lotes.c.id, _lotes.c.nombre)).all())
    eventos = conexion.execute(
        sa.select(_eventos.c.id, _eventos.c.establecimiento_id, _eventos.c.lote_id, _eventos.c.lote_destino_id)
    ).all()
    for evento_id, campo_id, lote_id, destino_id in eventos:
        if campo_id is None and lote_id is None and destino_id is None:
            continue
        nombre, clave = campos.get(campo_id, (None, None)) if campo_id else (None, None)
        conexion.execute(
            sa.update(_eventos)
            .where(_eventos.c.id == evento_id)
            .values(
                establecimiento=nombre,
                establecimiento_clave=clave,
                lote=lotes.get(lote_id),
                lote_destino=lotes.get(destino_id),
            )
        )
    for usuario_id, campo_id in conexion.execute(
        sa.select(_usuarios.c.id, _usuarios.c.establecimiento_actual_id).where(
            _usuarios.c.establecimiento_actual_id.is_not(None)
        )
    ).all():
        conexion.execute(
            sa.update(_usuarios).where(_usuarios.c.id == usuario_id).values(establecimiento_actual=campos[campo_id][0])
        )

    with op.batch_alter_table("usuarios") as t:
        t.drop_constraint("usuarios_establecimiento_actual_id_fkey", type_="foreignkey")
        t.drop_column("establecimiento_actual_id")
    with op.batch_alter_table("eventos") as t:
        for columna, _ in reversed(_REFERENCIAS):
            t.drop_index(f"ix_eventos_{columna}")
            t.drop_constraint(f"eventos_{columna}_fkey", type_="foreignkey")
            t.drop_column(columna)
    op.drop_index("ix_lotes_establecimiento_id", table_name="lotes")
    op.drop_index("ix_lotes_cuenta_id", table_name="lotes")
    op.drop_table("lotes")
    op.drop_index("ix_establecimientos_cuenta_id", table_name="establecimientos")
    op.drop_table("establecimientos")
