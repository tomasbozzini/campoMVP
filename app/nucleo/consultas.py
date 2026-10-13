"""Totales de una consulta. Las cuentas se hacen acá, en código: la IA nunca ve los datos."""

from collections import defaultdict

from app.infra.modelos import Evento


def totales(eventos: list[Evento]) -> tuple[dict[str, int], dict[tuple[str, str], float]]:
    """Animales por tipo de evento y suma de valores por (tipo, unidad)."""
    animales: dict[str, int] = defaultdict(int)
    valores: dict[tuple[str, str], float] = defaultdict(float)
    for e in eventos:
        if e.cantidad_animales:
            animales[e.tipo] += e.cantidad_animales
        if e.valor is not None and e.unidad:
            valores[(e.tipo, e.unidad)] += e.valor
    return dict(animales), dict(valores)
