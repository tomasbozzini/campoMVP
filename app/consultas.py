"""Busca eventos en la base a partir de los filtros que arma el modelo.

El modelo nunca escribe SQL: solo devuelve filtros, y la búsqueda siempre queda
restringida al campo del usuario.
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Evento

MAX_EVENTOS = 60


def normalizar_lote(lote: str | None) -> str | None:
    if not lote:
        return None
    lote = str(lote).strip().lower()
    for prefijo in ("el lote ", "lote ", "lote n°", "lote nro "):
        if lote.startswith(prefijo):
            lote = lote[len(prefijo) :].strip()
    return lote or None


def _fecha(valor) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        return None


def buscar(db: Session, campo_id: int, filtros: dict) -> dict:
    q = select(Evento).where(Evento.campo_id == campo_id)

    if filtros.get("categoria"):
        q = q.where(Evento.categoria == str(filtros["categoria"]).lower())
    if filtros.get("tipo"):
        q = q.where(Evento.tipo == str(filtros["tipo"]).lower())
    if lote := normalizar_lote(filtros.get("lote")):
        q = q.where((Evento.lote == lote) | (Evento.lote_destino == lote))
    if filtros.get("caravana"):
        q = q.where(func.lower(Evento.caravana) == str(filtros["caravana"]).lower())
    if filtros.get("categoria_animal"):
        raiz = str(filtros["categoria_animal"]).lower().rstrip("s")
        q = q.where(func.lower(Evento.categoria_animal).like(f"%{raiz}%"))
    if filtros.get("producto"):
        texto = f"%{str(filtros['producto']).lower()}%"
        q = q.where(
            func.lower(Evento.producto).like(texto) | func.lower(Evento.descripcion).like(texto)
        )
    if desde := _fecha(filtros.get("desde")):
        q = q.where(Evento.fecha_evento >= desde)
    if hasta := _fecha(filtros.get("hasta")):
        q = q.where(Evento.fecha_evento <= hasta)

    eventos = db.scalars(q.order_by(Evento.fecha_evento.desc(), Evento.id.desc())).all()

    # Los totales se calculan acá y no en el modelo, que suele equivocarse sumando.
    animales_por_tipo: dict[str, int] = defaultdict(int)
    valores: dict[str, float] = defaultdict(float)
    for e in eventos:
        if e.cantidad_animales:
            animales_por_tipo[e.tipo] += e.cantidad_animales
        if e.valor is not None and e.unidad:
            valores[f"{e.tipo} ({e.unidad})"] += e.valor

    return {
        "filtros": filtros,
        "total_registros": len(eventos),
        "total_animales_por_tipo": dict(animales_por_tipo),
        "suma_valores_por_tipo": dict(valores),
        "registros_mostrados": len(eventos[:MAX_EVENTOS]),
        "registros": [a_dict(e) for e in eventos[:MAX_EVENTOS]],
    }


def a_dict(e: Evento) -> dict:
    campos = (
        "categoria", "tipo", "descripcion", "producto", "dosis", "cantidad_animales",
        "categoria_animal", "caravana", "lote", "lote_destino", "valor", "unidad", "fecha_evento",
    )
    return {c: getattr(e, c) for c in campos if getattr(e, c) is not None}
