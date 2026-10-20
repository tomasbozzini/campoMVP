"""Modo prueba del administrador (paso 9a del plan)."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.ia import interprete
from app.infra.config import config
from app.infra.modelos import Evento, Prueba, Usuario
from app.nucleo import comandos, pipeline, pruebas
from tests.ayudas import con_perfil

HOY = date(2026, 10, 20)
ADMIN = "5492494000001"
OTRO = "5491100000002"
LLUVIA = {
    "intencion": "registrar",
    "establecimiento": "Omu",
    "eventos": [{"categoria": "campo", "tipo": "lluvia", "valor": 5, "unidad": "mm"}],
}


@pytest.fixture
def ia(monkeypatch):
    dichas: dict[str, object] = {
        "llovió 5 mm en omu": LLUVIA,
        "modo prueba": {"intencion": "aclarar"},  # para quien no es administrador, es un mensaje más
        "hola": {"intencion": "saludo"},
    }
    monkeypatch.setattr(config, "admin_telefonos", {ADMIN})
    monkeypatch.setattr(pipeline, "_ahora", lambda: datetime(2026, 10, 20, 15, 0, tzinfo=UTC))
    monkeypatch.setattr(interprete, "interpretar", lambda texto, *_a, **_k: dichas[texto.lower()])
    return dichas


def _mandar(db, telefono, texto, audio=False):
    return pipeline.atender(db, telefono, texto, hoy=HOY, audio=audio).texto


def _pruebas(db) -> list[Prueba]:
    return list(db.scalars(select(Prueba).order_by(Prueba.id)))


def test_guarda_lo_que_vio_y_devolvio_la_ia_y_lo_que_respondio(db, ia):
    con_perfil(db, ADMIN)
    assert _mandar(db, ADMIN, "Modo prueba") == pruebas.PRENDIDO
    assert _mandar(db, ADMIN, "modo prueba") == pruebas.YA_PRENDIDO
    respuesta = _mandar(db, ADMIN, "llovió 5 mm en Omu", audio=True)
    _mandar(db, ADMIN, "hola")

    primera, segunda = _pruebas(db)
    assert (primera.texto, primera.audio, primera.hoy, primera.pregunta) == ("llovió 5 mm en Omu", True, HOY, None)
    assert primera.interpretacion == LLUVIA and primera.respuesta == respuesta
    assert primera.historial == []
    # La segunda vio la charla de la primera, como la vio la IA.
    assert segunda.historial == [["usuario", "llovió 5 mm en Omu"], ["bot", respuesta]]
    assert segunda.audio is False and segunda.interpretacion == {"intencion": "saludo"}

    r = _mandar(db, ADMIN, "fin modo prueba")
    assert r.startswith("🧪 *MODO PRUEBA TERMINADO*\n\nHay 2 mensajes guardados en modo prueba.")
    _mandar(db, ADMIN, "hola")
    assert len(_pruebas(db)) == 2
    assert _mandar(db, ADMIN, "fin modo prueba") == pruebas.NO_ESTABA


def test_lo_que_no_va_a_la_ia_no_se_guarda(db, ia):
    con_perfil(db, ADMIN)
    _mandar(db, ADMIN, "modo prueba")
    _mandar(db, ADMIN, "mis campos")  # atajo
    _mandar(db, ADMIN, "invitar")  # comando del administrador
    assert _pruebas(db) == []


def test_guarda_la_pregunta_abierta(db, ia):
    """Un mensaje que no contesta la pregunta va a la IA con la pregunta: se guarda la clave."""
    usuario = con_perfil(db, ADMIN)
    _mandar(db, ADMIN, "llovió 5 mm en Omu")
    _mandar(db, ADMIN, "modo prueba")
    ia["sacá lo último"] = {"intencion": "borrar", "borrado": {"registros": []}}
    _mandar(db, ADMIN, "sacá lo último")  # pregunta si borra
    _mandar(db, ADMIN, "hola")
    assert [p.pregunta for p in _pruebas(db)] == [None, "borrar"]
    assert db.scalar(select(Usuario.modo_prueba).where(Usuario.id == usuario.id)) is True


def test_solo_el_administrador(db, ia, monkeypatch):
    con_perfil(db, OTRO)
    assert _mandar(db, OTRO, "modo prueba") != pruebas.PRENDIDO  # va a la IA como cualquier mensaje
    assert db.scalar(select(Usuario.modo_prueba).where(Usuario.telefono == OTRO)) is False
    # Si el número deja de ser administrador con el modo prendido, ya no se guarda.
    con_perfil(db, ADMIN)
    _mandar(db, ADMIN, "modo prueba")
    monkeypatch.setattr(config, "admin_telefonos", set())
    _mandar(db, ADMIN, "hola")
    assert _pruebas(db) == []


def test_borrar_mis_datos_borra_las_pruebas(db, ia):
    con_perfil(db, ADMIN)
    _mandar(db, ADMIN, "modo prueba")
    _mandar(db, ADMIN, "llovió 5 mm en Omu")
    assert len(_pruebas(db)) == 1
    _mandar(db, ADMIN, comandos.CONFIRMAR_BORRAR_DATOS)
    assert _pruebas(db) == [] and db.scalars(select(Evento)).all() == []


def test_la_ayuda_del_administrador_muestra_el_modo_prueba():
    assert "*modo prueba*" in comandos.ayuda(es_admin=True)
    assert "modo prueba" not in comandos.ayuda(es_admin=False)
