"""Base: el esquema tal como estaba antes de usar Alembic (creado con create_all).

Revisión: 0001
Anterior: ninguna
Fecha: 2026-10-13 17:47:12.701782
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "cotizaciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rubro", sa.String(length=20), nullable=False),
        sa.Column("producto", sa.String(length=40), nullable=False),
        sa.Column("plaza", sa.String(length=60), nullable=True),
        sa.Column("valor", sa.Float(), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("unidad", sa.String(length=20), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("incluye_impuestos", sa.Boolean(), nullable=True),
        sa.Column("costos_adicionales", sa.String(length=300), nullable=True),
        sa.Column("fuente", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=300), nullable=False),
        sa.Column("obtenido", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fuente", "producto", "plaza", "fecha"),
    )
    with op.batch_alter_table("cotizaciones", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_cotizaciones_fecha"), ["fecha"], unique=False)
        batch_op.create_index(batch_op.f("ix_cotizaciones_producto"), ["producto"], unique=False)
        batch_op.create_index(batch_op.f("ix_cotizaciones_rubro"), ["rubro"], unique=False)

    op.create_table(
        "mensajes_procesados",
        sa.Column("wamid", sa.String(length=128), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("wamid"),
    )
    op.create_table(
        "productos_veterinarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("nombre_busqueda", sa.String(length=200), nullable=False),
        sa.Column("registro", sa.String(length=40), nullable=False),
        sa.Column("titular", sa.String(length=200), nullable=True),
        sa.Column("principio_activo", sa.String(length=300), nullable=True),
        sa.Column("principio_busqueda", sa.String(length=300), nullable=True),
        sa.Column("estado", sa.String(length=40), nullable=True),
        sa.Column("fecha_datos", sa.Date(), nullable=False),
        sa.Column("fuente", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=300), nullable=False),
        sa.Column("obtenido", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("productos_veterinarios", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_productos_veterinarios_nombre"), ["nombre"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_productos_veterinarios_nombre_busqueda"), ["nombre_busqueda"], unique=False
        )

    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telefono", sa.String(length=20), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=True),
        sa.Column("autorizado", sa.Boolean(), nullable=False),
        sa.Column("establecimiento_actual", sa.String(length=120), nullable=True),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_usuarios_telefono"), ["telefono"], unique=True)

    op.create_table(
        "borrados_pendientes",
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("ids", sa.JSON(), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
        ),
        sa.PrimaryKeyConstraint("usuario_id"),
    )
    op.create_table(
        "eventos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("establecimiento", sa.String(length=120), nullable=True),
        sa.Column("establecimiento_clave", sa.String(length=120), nullable=True),
        sa.Column("mensaje_id", sa.String(length=36), nullable=True),
        sa.Column("categoria", sa.String(length=20), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("producto", sa.String(length=120), nullable=True),
        sa.Column("dosis", sa.String(length=60), nullable=True),
        sa.Column("cantidad_animales", sa.Integer(), nullable=True),
        sa.Column("categoria_animal", sa.String(length=40), nullable=True),
        sa.Column("caravana", sa.String(length=40), nullable=True),
        sa.Column("lote", sa.String(length=60), nullable=True),
        sa.Column("lote_destino", sa.String(length=60), nullable=True),
        sa.Column("valor", sa.Float(), nullable=True),
        sa.Column("unidad", sa.String(length=20), nullable=True),
        sa.Column("fecha_evento", sa.Date(), nullable=False),
        sa.Column("confianza", sa.String(length=10), nullable=True),
        sa.Column("mensaje_original", sa.Text(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("eventos", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_eventos_caravana"), ["caravana"], unique=False)
        batch_op.create_index(batch_op.f("ix_eventos_categoria"), ["categoria"], unique=False)
        batch_op.create_index(batch_op.f("ix_eventos_establecimiento_clave"), ["establecimiento_clave"], unique=False)
        batch_op.create_index(batch_op.f("ix_eventos_fecha_evento"), ["fecha_evento"], unique=False)
        batch_op.create_index(batch_op.f("ix_eventos_lote"), ["lote"], unique=False)
        batch_op.create_index(batch_op.f("ix_eventos_mensaje_id"), ["mensaje_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_eventos_tipo"), ["tipo"], unique=False)
        batch_op.create_index(batch_op.f("ix_eventos_usuario_id"), ["usuario_id"], unique=False)

    op.create_table(
        "mensajes_chat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("rol", sa.String(length=10), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("mensajes_chat", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_mensajes_chat_creado"), ["creado"], unique=False)
        batch_op.create_index(batch_op.f("ix_mensajes_chat_usuario_id"), ["usuario_id"], unique=False)

    op.create_table(
        "uso_diario",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("usuario_id", "fecha"),
    )
    with op.batch_alter_table("uso_diario", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_uso_diario_usuario_id"), ["usuario_id"], unique=False)


def downgrade() -> None:

    with op.batch_alter_table("uso_diario", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_uso_diario_usuario_id"))

    op.drop_table("uso_diario")
    with op.batch_alter_table("mensajes_chat", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_mensajes_chat_usuario_id"))
        batch_op.drop_index(batch_op.f("ix_mensajes_chat_creado"))

    op.drop_table("mensajes_chat")
    with op.batch_alter_table("eventos", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_eventos_usuario_id"))
        batch_op.drop_index(batch_op.f("ix_eventos_tipo"))
        batch_op.drop_index(batch_op.f("ix_eventos_mensaje_id"))
        batch_op.drop_index(batch_op.f("ix_eventos_lote"))
        batch_op.drop_index(batch_op.f("ix_eventos_fecha_evento"))
        batch_op.drop_index(batch_op.f("ix_eventos_establecimiento_clave"))
        batch_op.drop_index(batch_op.f("ix_eventos_categoria"))
        batch_op.drop_index(batch_op.f("ix_eventos_caravana"))

    op.drop_table("eventos")
    op.drop_table("borrados_pendientes")
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_usuarios_telefono"))

    op.drop_table("usuarios")
    with op.batch_alter_table("productos_veterinarios", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_productos_veterinarios_nombre_busqueda"))
        batch_op.drop_index(batch_op.f("ix_productos_veterinarios_nombre"))

    op.drop_table("productos_veterinarios")
    op.drop_table("mensajes_procesados")
    with op.batch_alter_table("cotizaciones", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_cotizaciones_rubro"))
        batch_op.drop_index(batch_op.f("ix_cotizaciones_producto"))
        batch_op.drop_index(batch_op.f("ix_cotizaciones_fecha"))

    op.drop_table("cotizaciones")
