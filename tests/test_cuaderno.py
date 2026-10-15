"""Aislamiento: cada cuenta solo ve y toca lo suyo, y solo el cuaderno filtra por cuenta o usuario."""

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.infra.modelos import BorradoPendiente, Evento, MensajeChat, UsoDiario, Usuario
from app.nucleo import usuarios
from app.nucleo.cuaderno import Cuaderno, Filtros

HOY = date(2026, 10, 13)


@pytest.fixture
def dos(db):
    """Dos personas con un registro cada una."""
    a = Cuaderno(db, usuarios.autorizar(db, "5491100000001"))
    b = Cuaderno(db, usuarios.autorizar(db, "5491100000002"))
    a.agregar([Evento(categoria="campo", tipo="lluvia", valor=10, unidad="mm", fecha_evento=HOY, mensaje_id="m1")])
    b.agregar([Evento(categoria="campo", tipo="lluvia", valor=99, unidad="mm", fecha_evento=HOY, mensaje_id="m1")])
    return a, b


def _ids(db, usuario_id):
    return [e.id for e in db.scalars(select(Evento).where(Evento.usuario_id == usuario_id))]


def test_cada_cuaderno_lee_solo_lo_suyo(db, dos):
    a, b = dos
    assert [e.valor for e in a.recientes(10)] == [10]
    assert [e.valor for e in a.buscar(Filtros())] == [10]
    assert [e.valor for e in a.del_mensaje("m1")] == [10]  # mismo mensaje_id, otra persona
    assert a.ultimo() is not None and a.ultimo().valor == 10
    assert a.cantidad() == 1 and b.cantidad() == 1


def test_no_se_puede_borrar_lo_de_otro_aunque_venga_el_id(db, dos):
    a, b = dos
    assert a.borrar(_ids(db, b.usuario_id)) == 0
    assert b.cantidad() == 1
    assert a.borrar(_ids(db, a.usuario_id)) == 1


def test_agregar_asigna_siempre_el_dueno_del_cuaderno(db, dos):
    a, b = dos
    a.agregar(
        [Evento(cuenta_id=b.cuenta_id, usuario_id=b.usuario_id, categoria="campo", tipo="lluvia", fecha_evento=HOY)]
    )
    assert a.cantidad() == 2 and b.cantidad() == 1


def test_cada_persona_tiene_su_propia_cuenta(db, dos):
    a, b = dos
    assert a.cuenta_id != b.cuenta_id


def test_los_registros_son_de_la_cuenta_y_la_charla_de_cada_persona(db, dos):
    """Preparado para un estudio con varios profesionales: comparten registros, no la charla."""
    a, _ = dos
    duenio = db.get(Usuario, a.usuario_id)
    colega = Usuario(telefono="5491100000003", autorizado=True, cuenta_id=duenio.cuenta_id)
    db.add(colega)
    db.flush()
    c = Cuaderno(db, colega)
    assert [e.valor for e in c.recientes(10)] == [10]
    c.agregar([Evento(categoria="campo", tipo="lluvia", valor=5, unidad="mm", fecha_evento=HOY)])
    assert a.cantidad() == 2
    assert db.scalar(select(Evento).where(Evento.valor == 5)).usuario_id == colega.id  # quién lo anotó

    hace_un_rato = datetime.now(UTC) - timedelta(minutes=5)
    a.guardar_charla([("usuario", "hola")], conservar=4)
    assert c.charla(hace_un_rato, 6) == []


def test_charla_cupo_y_borrado_pendiente_son_por_persona(db, dos):
    a, b = dos
    a.guardar_charla([("usuario", "hola"), ("bot", "¡Hola!")], conservar=4)
    hace_un_rato = datetime.now(UTC) - timedelta(minutes=5)
    assert [m.texto for m in a.charla(hace_un_rato, 6)] == ["hola", "¡Hola!"]
    assert b.charla(hace_un_rato, 6) == []

    assert a.consumir_cupo(HOY, limite=1) is True
    assert a.consumir_cupo(HOY, limite=1) is False
    assert b.consumir_cupo(HOY, limite=1) is True

    a.guardar_borrado_pendiente([1, 2], datetime.now(UTC))
    assert b.tomar_borrado_pendiente() is None
    pendiente = a.tomar_borrado_pendiente()
    assert pendiente is not None and pendiente.ids == [1, 2]
    assert a.tomar_borrado_pendiente() is None  # se usa una sola vez


def test_la_charla_guarda_solo_los_ultimos(db, dos):
    a, _ = dos
    for i in range(5):
        a.guardar_charla([("usuario", f"m{i}")], conservar=3)
    assert [m.texto for m in db.scalars(select(MensajeChat).order_by(MensajeChat.id))] == ["m2", "m3", "m4"]


def test_borrar_todo_no_toca_a_los_demas(db, dos):
    a, b = dos
    for c in (a, b):
        c.guardar_charla([("usuario", "hola")], conservar=4)
        c.consumir_cupo(HOY, limite=5)
        c.guardar_borrado_pendiente([1], datetime.now(UTC))
    a.borrar_todo()
    for modelo in (Evento, MensajeChat, UsoDiario, BorradoPendiente):
        duenos = {f.usuario_id for f in db.scalars(select(modelo))}
        assert duenos == {b.usuario_id}, modelo


def test_solo_el_cuaderno_filtra_por_usuario():
    """Ningún otro módulo arma consultas por cuenta o por usuario a mano: el aislamiento vive
    en un solo lugar."""
    raiz = Path(__file__).parent.parent / "app"
    tablas = r"(Evento|Establecimiento|Lote|Sesion|MensajeChat|UsoDiario|BorradoPendiente)\.(usuario_id|cuenta_id)"
    fuera = [
        str(archivo.relative_to(raiz))
        for archivo in raiz.rglob("*.py")
        if archivo.name not in ("cuaderno.py", "modelos.py") and re.search(tablas, archivo.read_text(encoding="utf-8"))
    ]
    assert fuera == []
