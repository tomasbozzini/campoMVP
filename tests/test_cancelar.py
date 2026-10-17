"""Cancelar una pregunta del bot con cualquier frase (paso 8.5 del plan).

Primero las variantes fijas, sin IA. Si no coinciden, la IA recibe la pregunta pendiente y
puede devolver "cancelar". Si el mensaje es otro pedido, sigue su camino. Nunca se contesta
con el saludo.
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.ia import interprete
from app.infra.modelos import Evento
from app.modulos.comun import campos, conversacion
from app.nucleo import perfil, pipeline, preguntas
from app.nucleo.cuaderno import Cuaderno
from tests.ayudas import con_perfil

HOY = date(2026, 10, 15)
TEL = "5491100000001"


@pytest.fixture
def ia(monkeypatch):
    """La IA falsa: cada texto tiene su respuesta; `pedidos` guarda la pregunta que recibió."""
    respuestas: dict[str, object] = {"mostrame mis campos": {"intencion": "mis_campos"}}
    pedidos: list[tuple[str, str | None]] = []

    def interpretar(texto, *_a, pregunta=None, **_k):
        pedidos.append((texto, pregunta))
        return respuestas[texto]

    monkeypatch.setattr(pipeline, "_ahora", lambda: datetime(2026, 10, 15, 12, 0, tzinfo=UTC))
    monkeypatch.setattr(interprete, "interpretar", interpretar)
    return respuestas, pedidos


def _mandar(db, texto):
    return pipeline.manejar_mensaje(db, TEL, texto, hoy=HOY)


@pytest.mark.parametrize(
    "texto", ["No, no, dejá, no quiero cambiar nada.", "no quiero", "olvidate", "no, dejalo como está", "mejor no"]
)
def test_las_variantes_fijas_cancelan_sin_ia(db, ia, texto):
    _, pedidos = ia
    u = con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, "cambiar rubro")
    assert _mandar(db, texto) == perfil.SIN_CAMBIOS
    assert pedidos == [] and u.rubro == "veterinario" and u.pregunta is None


def test_si_no_es_una_variante_fija_la_ia_ve_la_pregunta_y_cancela(db, ia):
    respuestas, pedidos = ia
    u = con_perfil(db, TEL, rubro="veterinario")
    respuestas["ehh mirá, mejor lo dejo como lo tenía"] = {"intencion": "cancelar"}
    _mandar(db, "cambiar rubro")
    assert _mandar(db, "ehh mirá, mejor lo dejo como lo tenía") == perfil.SIN_CAMBIOS
    assert pedidos == [("ehh mirá, mejor lo dejo como lo tenía", preguntas.para_la_ia(preguntas.RUBRO))]
    assert u.rubro == "veterinario"


def test_con_una_pregunta_pendiente_nunca_contesta_el_saludo(db, ia):
    respuestas, _ = ia
    con_perfil(db, TEL)
    respuestas["nono"] = {"intencion": "saludo"}  # como pasó con el audio en el celular
    _mandar(db, "cambiar matrícula")
    r = _mandar(db, "nono")
    assert r == perfil.SIN_CAMBIOS and r != conversacion.SALUDO


def test_sin_pregunta_pendiente_el_saludo_es_el_saludo(db, ia):
    respuestas, pedidos = ia
    con_perfil(db, TEL)
    respuestas["buenas"] = {"intencion": "saludo"}
    assert _mandar(db, "buenas") == conversacion.SALUDO
    assert pedidos == [("buenas", None)]


def test_si_es_otro_pedido_la_pregunta_se_descarta_y_sigue_su_camino(db, ia):
    _, pedidos = ia
    u = con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, "cambiar rubro")
    assert _mandar(db, "mostrame mis campos") == campos.mis_campos(Cuaderno(db, u), u)
    assert pedidos[-1][1] == preguntas.para_la_ia(preguntas.RUBRO)
    assert u.pregunta is None and u.rubro == "veterinario"


def test_cancelar_un_borrado_grande_con_otras_palabras(db, ia):
    respuestas, pedidos = ia
    u = con_perfil(db, TEL)
    Cuaderno(db, u).agregar(
        [Evento(categoria="campo", tipo="lluvia", valor=10 + i, fecha_evento=HOY) for i in range(4)]
    )
    respuestas["borrá todo"] = {"intencion": "borrar", "borrado": {"registros": [{"todos": True}]}}
    respuestas["uy pará, me equivoqué de cuaderno"] = {"intencion": "cancelar"}
    assert "VOY A BORRAR 4 REGISTROS" in _mandar(db, "borrá todo")
    assert _mandar(db, "uy pará, me equivoqué de cuaderno") == "👌 Listo, no borré nada."
    assert pedidos[-1][1] == preguntas.para_la_ia(preguntas.BORRAR)
    assert len(db.scalars(select(Evento)).all()) == 4


def test_cancelar_sin_pregunta_pendiente_no_hace_nada(db, ia):
    respuestas, _ = ia
    con_perfil(db, TEL)
    respuestas["cancelá"] = {"intencion": "cancelar"}
    assert _mandar(db, "cancelá") == "👌 Listo."
