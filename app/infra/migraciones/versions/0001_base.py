"""Base: el esquema tal como estaba antes de usar Alembic (creado con create_all).

Las tablas se definen acá, congeladas, y no se importan de los modelos: así esta migración
crea siempre lo mismo aunque los modelos cambien, y `esquema` sirve de referencia para
adoptar las bases creadas antes de Alembic (ver app/infra/migrar.py). No se modifica:
los cambios van en migraciones nuevas.

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

esquema = sa.MetaData()

sa.Table(
    "usuarios",
    esquema,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("telefono", sa.String(length=20), nullable=False),
    sa.Column("nombre", sa.String(length=120), nullable=True),
    sa.Column("autorizado", sa.Boolean(), nullable=False),
    sa.Column("establecimiento_actual", sa.String(length=120), nullable=True),
    sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_usuarios_telefono", "telefono", unique=True),
)

sa.Table(
    "eventos",
    esquema,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
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
    sa.Index("ix_eventos_caravana", "caravana"),
    sa.Index("ix_eventos_categoria", "categoria"),
    sa.Index("ix_eventos_establecimiento_clave", "establecimiento_clave"),
    sa.Index("ix_eventos_fecha_evento", "fecha_evento"),
    sa.Index("ix_eventos_lote", "lote"),
    sa.Index("ix_eventos_mensaje_id", "mensaje_id"),
    sa.Index("ix_eventos_tipo", "tipo"),
    sa.Index("ix_eventos_usuario_id", "usuario_id"),
)

sa.Table(
    "mensajes_procesados",
    esquema,
    sa.Column("wamid", sa.String(length=128), primary_key=True),
    sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
)

sa.Table(
    "cotizaciones",
    esquema,
    sa.Column("id", sa.Integer(), primary_key=True),
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
    sa.UniqueConstraint("fuente", "producto", "plaza", "fecha"),
    sa.Index("ix_cotizaciones_fecha", "fecha"),
    sa.Index("ix_cotizaciones_producto", "producto"),
    sa.Index("ix_cotizaciones_rubro", "rubro"),
)

sa.Table(
    "uso_diario",
    esquema,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
    sa.Column("fecha", sa.Date(), nullable=False),
    sa.Column("cantidad", sa.Integer(), nullable=False),
    sa.UniqueConstraint("usuario_id", "fecha"),
    sa.Index("ix_uso_diario_usuario_id", "usuario_id"),
)

sa.Table(
    "productos_veterinarios",
    esquema,
    sa.Column("id", sa.Integer(), primary_key=True),
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
    sa.Index("ix_productos_veterinarios_nombre", "nombre"),
    sa.Index("ix_productos_veterinarios_nombre_busqueda", "nombre_busqueda"),
)

sa.Table(
    "mensajes_chat",
    esquema,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
    sa.Column("rol", sa.String(length=10), nullable=False),
    sa.Column("texto", sa.Text(), nullable=False),
    sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_mensajes_chat_creado", "creado"),
    sa.Index("ix_mensajes_chat_usuario_id", "usuario_id"),
)

sa.Table(
    "borrados_pendientes",
    esquema,
    sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), primary_key=True),
    sa.Column("ids", sa.JSON(), nullable=False),
    sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
)


def upgrade() -> None:
    esquema.create_all(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    esquema.drop_all(op.get_bind(), checkfirst=False)
