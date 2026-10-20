"""Registro de acciones sensibles (altas, bajas, invitaciones, borrados).

Guarda solo ids numéricos y cantidades. Se consulta desde la terminal:
python -m app auditoria
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.modelos import Auditoria

AUTORIZAR = "autorizar"
QUITAR = "quitar"
BORRAR_DATOS = "borrar_datos"
BORRAR_REGISTROS = "borrar_registros"
BORRAR_PENDIENTES = "borrar_pendientes"
RENOMBRAR_CAMPO = "renombrar_campo"
UNIR_CAMPOS = "unir_campos"
RENOMBRAR_LOTE = "renombrar_lote"
UNIR_LOTES = "unir_lotes"
BORRAR_CAMPO = "borrar_campo"
BORRAR_LOTE = "borrar_lote"
INVITAR = "invitar"
ANULAR = "anular"
ALTA = "alta"
ALTA_VENCIDA = "alta_vencida"


def registrar(db: Session, accion: str, actor: int | None = None, sobre: int | None = None, **detalle: int) -> None:
    db.add(Auditoria(accion=accion, actor=actor, sobre=sobre, detalle=detalle or None))
    db.flush()


def ultimas(db: Session, limite: int = 50) -> list[Auditoria]:
    """Las últimas acciones, de la más nueva a la más vieja."""
    return list(db.scalars(select(Auditoria).order_by(Auditoria.id.desc()).limit(limite)).all())
