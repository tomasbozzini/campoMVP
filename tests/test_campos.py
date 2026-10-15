"""Establecimientos y lotes como tablas de la cuenta, y el comando "mis campos"."""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.ia import interprete
from app.infra.modelos import Establecimiento, Evento, Lote
from app.nucleo import pipeline
from app.nucleo.cuaderno import Cuaderno
from tests.ayudas import con_perfil

HOY = date(2026, 10, 15)
TEL, OTRO = "5491100000001", "5491100000002"


@pytest.fixture
def ia(monkeypatch):
    """La IA falsa: cada texto tiene su respuesta. Anota qué textos le llegaron."""
    respuestas: dict[str, dict] = {}
    llamadas: list[str] = []

    def interpretar(texto, hoy, historial=None, partes=()):
        llamadas.append(texto)
        return respuestas[texto]

    monkeypatch.setattr(interprete, "interpretar", interpretar)
    return respuestas, llamadas


def _mandar(db, texto, telefono=TEL):
    return pipeline.manejar_mensaje(db, telefono, texto, hoy=HOY)


def _registrar(respuestas, texto, establecimiento=None, **evento):
    respuestas[texto] = {
        "intencion": "registrar",
        "establecimiento": establecimiento,
        "eventos": [{"categoria": "sanidad", "tipo": "vacunacion", "cantidad_animales": 10, **evento}],
    }


def _cuantos(db, modelo):
    return db.scalar(select(func.count()).select_from(modelo))


def test_el_mismo_campo_escrito_distinto_es_uno_solo(db, ia):
    respuestas, _ = ia
    con_perfil(db, TEL)
    respuestas["estoy en la esperanza"] = {"intencion": "establecimiento", "establecimiento": "La Esperanza"}
    _registrar(respuestas, "vacuné en la estancia", "Estancia LA ESPERANZA", lote="Lote 3")
    _registrar(respuestas, "vacuné de nuevo", "la esperanza", lote="3")

    assert "📍 *La Esperanza*" in _mandar(db, "estoy en la esperanza")
    assert "📍 La Esperanza" in _mandar(db, "vacuné en la estancia")  # con el nombre de la primera vez
    _mandar(db, "vacuné de nuevo")

    assert _cuantos(db, Establecimiento) == 1 and _cuantos(db, Lote) == 1
    eventos = db.scalars(select(Evento)).all()
    assert {(e.nombre_establecimiento, e.nombre_lote) for e in eventos} == {("La Esperanza", "3")}


def test_cada_lote_es_de_su_campo(db, ia):
    """El lote 3 de La Esperanza y el de El Ombú son distintos; el que se nombró sin campo queda suelto."""
    respuestas, _ = ia
    u = con_perfil(db, TEL)
    _registrar(respuestas, "sin campo", lote="3")
    _registrar(respuestas, "en la esperanza", "La Esperanza", lote="3")
    _registrar(respuestas, "en el ombu", "El Ombú", lote="3")
    _registrar(respuestas, "traslado", "El Ombú", tipo="traslado", lote="3", lote_destino="5")
    for texto in ("sin campo", "en la esperanza", "en el ombu", "traslado"):
        _mandar(db, texto)

    lotes = db.execute(select(Lote.establecimiento_id, Lote.nombre)).all()
    assert len(lotes) == 4 and sum(1 for campo, _ in lotes if campo is None) == 1
    traslado = db.scalar(select(Evento).where(Evento.tipo == "traslado"))
    assert traslado.lote.establecimiento_id == traslado.lote_destino.establecimiento_id == traslado.establecimiento_id
    assert u.establecimiento_actual is not None and u.establecimiento_actual.nombre == "El Ombú"


def test_mis_campos_lista_campos_lotes_y_registros_sin_ia(db, ia):
    respuestas, llamadas = ia
    con_perfil(db, TEL)
    _registrar(respuestas, "a", "La Esperanza", lote="10")
    _registrar(respuestas, "b", "La Esperanza", lote="2")
    _registrar(respuestas, "c", "La Esperanza", lote="potrero grande")
    _registrar(respuestas, "d", "El Ombú")
    for texto in ("a", "b", "c", "d"):
        _mandar(db, texto)
    llamadas.clear()

    r = _mandar(db, "Mis campos")
    assert llamadas == []
    assert r.index("*El Ombú* · 1 registro · _estás acá_") < r.index("*La Esperanza* · 3 registros")
    assert "Lotes: 2, 10, potrero grande" in r
    assert "Sin establecimiento" not in r


def test_mis_campos_muestra_lo_que_no_tiene_campo(db, ia):
    respuestas, _ = ia
    con_perfil(db, TEL)
    _registrar(respuestas, "sin campo", lote="4")
    _mandar(db, "sin campo")
    assert "_Sin establecimiento_ · 1 registro\n      Lotes: 4" in _mandar(db, "mis lotes")


def test_mis_campos_sin_nada_anotado(db, ia):
    con_perfil(db, TEL)
    assert _mandar(db, "mis campos") == "📭 Todavía no anotaste nada en ningún campo.\n\n" + (
        "Decime dónde estás y lo que anotes queda ahí, por ejemplo: _estoy en La Esperanza_."
    )


def test_corregir_el_campo_mueve_el_lote_al_campo_nuevo(db, ia):
    respuestas, _ = ia
    con_perfil(db, TEL)
    _registrar(respuestas, "vacuné", "La Esperanza", lote="3")
    respuestas["fue en el ombú"] = {
        "intencion": "corregir",
        "correccion": {"referencia": {}, "cambios": {"establecimiento": "El Ombú"}},
    }
    _mandar(db, "vacuné")
    r = _mandar(db, "fue en el ombú")

    assert "Establecimiento: ~La Esperanza~ → *El Ombú*" in r
    evento = db.scalar(select(Evento))
    assert (evento.nombre_establecimiento, evento.nombre_lote) == ("El Ombú", "3")
    assert evento.lote.establecimiento_id == evento.establecimiento_id


def test_consultar_por_campo_escrito_distinto_y_por_lote(db, ia):
    respuestas, _ = ia
    con_perfil(db, TEL)
    _registrar(respuestas, "a", "La Esperanza", lote="3")
    _registrar(respuestas, "b", "El Ombú", lote="3")
    _registrar(respuestas, "c", "El Ombú", tipo="traslado", lote="1", lote_destino="3")
    for texto in ("a", "b", "c"):
        _mandar(db, texto)
    respuestas["¿qué hice en la estancia la esperanza?"] = {
        "intencion": "consultar",
        "consulta": {"establecimiento": "estancia la esperanza"},
    }
    respuestas["¿qué hice en el lote 3?"] = {"intencion": "consultar", "consulta": {"lote": "Lote 3"}}

    assert "📍 La Esperanza · 1 registro" in _mandar(db, "¿qué hice en la estancia la esperanza?")
    assert "3 registros" in _mandar(db, "¿qué hice en el lote 3?")  # de los dos campos, origen o destino


def test_cada_cuenta_tiene_sus_campos(db):
    """La misma estancia en dos cuentas son dos establecimientos: nadie ve lo del otro."""
    a, b = Cuaderno(db, con_perfil(db, TEL)), Cuaderno(db, con_perfil(db, OTRO))
    campo_a = a.establecimiento("La Pastora")
    campo_b = b.establecimiento("La Pastora")
    assert campo_a is not None and campo_b is not None and campo_a.id != campo_b.id
    a.lote("3", campo_a)
    assert [c.establecimiento.nombre for c in b.campos() if c.establecimiento] == ["La Pastora"]
    assert b.campos()[0].lotes == []
    with pytest.raises(ValueError, match="otra cuenta"):
        b.lote("3", campo_a)
