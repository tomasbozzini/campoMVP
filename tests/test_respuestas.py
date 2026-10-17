"""Respuestas cortas a una pregunta del bot (*sí* / *no*), sin IA, con sus variantes."""

import pytest

from app.nucleo import respuestas


@pytest.mark.parametrize(
    "texto",
    [
        "sí",
        "Sí!",
        "si",
        "SII",
        "dale",
        "Dale, borralos",
        "ok",
        "okey",
        "sí, borrá",
        "de una",
        "confirmo",
        "sí, borrá todo",
    ],
)
def test_variantes_del_si(texto):
    assert respuestas.es_si(texto) and not respuestas.es_no(texto)


@pytest.mark.parametrize(
    "texto", ["no", "No.", "no, dejá", "dejá", "dejalo así", "mejor no", "cancelá", "no, no borres nada", "nada"]
)
def test_variantes_del_no(texto):
    assert respuestas.es_no(texto) and not respuestas.es_si(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "dale, no",  # mezcla un sí y un no
        "no, borrá solo la de ayer",  # trae otra cosa: es otro pedido
        "sí, pero la de La Pastora",
        "vacuné 20 vacas",
        "bueno",  # solo relleno
        "",
    ],
)
def test_lo_que_no_es_una_respuesta(texto):
    assert not respuestas.es_si(texto) and not respuestas.es_no(texto)


@pytest.mark.parametrize(
    "texto",
    ["No, no, dejá, no quiero cambiar nada.", "no quiero", "olvidate", "nah", "no, pará", "no, es otro", "ninguno no"],
)
def test_mas_variantes_del_no(texto):
    assert respuestas.es_no(texto) and not respuestas.es_si(texto)


@pytest.mark.parametrize("texto", ["sí, es ese", "si el mismo", "dale, es esa"])
def test_mas_variantes_del_si(texto):
    assert respuestas.es_si(texto) and not respuestas.es_no(texto)


@pytest.mark.parametrize(
    ("texto", "cancela"),
    [("cancelá", True), ("no, dejá", True), ("olvidate", True), ("nada", True), ("no", False), ("no, es otro", False)],
)
def test_que_no_cancela_todo(texto, cancela):
    """En "¿*Omu* es *El Ombú*?", "no" es que es otro campo; "no, dejá", que no anote nada."""
    assert respuestas.es_cancelar(texto) is cancela
