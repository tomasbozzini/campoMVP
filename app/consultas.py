"""Busca eventos en la base a partir de los filtros que arma el modelo.

El modelo nunca escribe SQL ni ve los resultados: solo devuelve filtros, y la búsqueda
siempre queda restringida a los registros de quien pregunta.
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Evento

MAX_EVENTOS = 5000


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


def buscar(db: Session, usuario_id: int, filtros: dict) -> list[Evento]:
    q = select(Evento).where(Evento.usuario_id == usuario_id)

    if filtros.get("establecimiento"):  # ya viene normalizado (bot.clave_establecimiento)
        q = q.where(Evento.establecimiento_clave == filtros["establecimiento"])
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

    return list(db.scalars(q.order_by(Evento.fecha_evento.desc(), Evento.id.desc()).limit(MAX_EVENTOS)).all())


def totales(eventos: list[Evento]) -> tuple[dict[str, int], dict[tuple[str, str], float]]:
    """Animales por tipo de evento y suma de valores por (tipo, unidad).

    Las cuentas se hacen acá, en código: la IA nunca ve los datos guardados.
    """
    animales: dict[str, int] = defaultdict(int)
    valores: dict[tuple[str, str], float] = defaultdict(float)
    for e in eventos:
        if e.cantidad_animales:
            animales[e.tipo] += e.cantidad_animales
        if e.valor is not None and e.unidad:
            valores[(e.tipo, e.unidad)] += e.valor
    return dict(animales), dict(valores)
