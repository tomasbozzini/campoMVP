"""Auditoría: las acciones sensibles quedan registradas, solo con ids y cantidades."""

from datetime import date

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app import terminal
from app.ia import interprete
from app.infra import migrar
from app.infra.config import config
from app.infra.modelos import Auditoria, Usuario
from app.nucleo import auditoria, pipeline
from tests.ayudas import con_perfil

HOY = date(2026, 10, 15)
ADMIN, OTRO = "5492494000009", "5492494123456"


def _acciones(db) -> list[tuple[str, int | None, int | None, dict | None]]:
    return [(a.accion, a.actor, a.sobre, a.detalle) for a in db.scalars(select(Auditoria).order_by(Auditoria.id))]


def _sin_datos_personales(db, *datos: str) -> None:
    for fila in db.scalars(select(Auditoria)):
        assert all(isinstance(v, int) for v in (fila.detalle or {}).values())
        for dato in datos:
            assert dato not in f"{fila.accion} {fila.actor} {fila.sobre} {fila.detalle}"


@pytest.fixture
def ia(monkeypatch):
    respuestas: dict[str, dict] = {}
    monkeypatch.setattr(interprete, "interpretar", lambda texto, hoy, historial=None: respuestas[texto])
    return respuestas


def test_autorizar_y_quitar_por_whatsapp_quedan_con_el_admin(db, monkeypatch):
    monkeypatch.setattr(config, "admin_telefonos", {ADMIN})
    admin = con_perfil(db, ADMIN)
    db.execute(delete(Auditoria))  # el alta del admin de prueba no interesa acá

    pipeline.manejar_mensaje(db, ADMIN, f"autorizar {OTRO}", hoy=HOY)
    pipeline.manejar_mensaje(db, ADMIN, f"quitar {OTRO}", hoy=HOY)
    pipeline.manejar_mensaje(db, ADMIN, f"quitar {OTRO}", hoy=HOY)  # ya no tenía acceso: no cambia nada

    otro = db.scalar(select(Usuario).where(Usuario.telefono == OTRO))
    assert _acciones(db) == [
        (auditoria.AUTORIZAR, admin.id, otro.id, None),
        (auditoria.QUITAR, admin.id, otro.id, None),
    ]
    _sin_datos_personales(db, ADMIN, OTRO, "Juana")


def test_borrar_registros_queda_con_la_cantidad(db, ia):
    u = con_perfil(db, OTRO)
    ia["llovio"] = {"intencion": "registrar", "eventos": [{"categoria": "campo", "tipo": "lluvia", "valor": 20}]}
    pipeline.manejar_mensaje(db, OTRO, "llovio", hoy=HOY)
    pipeline.manejar_mensaje(db, OTRO, "borrar", hoy=HOY)

    assert _acciones(db)[-1] == (auditoria.BORRAR_REGISTROS, u.id, None, {"cuenta": u.cuenta_id, "cantidad": 1})
    _sin_datos_personales(db, OTRO, "lluvia", "llovio")


def test_borrar_mis_datos_deja_solo_los_ids(db, ia):
    u = con_perfil(db, OTRO)
    usuario_id, cuenta_id = u.id, u.cuenta_id
    ia["llovio"] = {"intencion": "registrar", "eventos": [{"categoria": "campo", "tipo": "lluvia", "valor": 20}]}
    pipeline.manejar_mensaje(db, OTRO, "llovio", hoy=HOY)
    pipeline.manejar_mensaje(db, OTRO, "borrar mis datos", hoy=HOY)
    pipeline.manejar_mensaje(db, OTRO, "confirmo borrar mis datos", hoy=HOY)

    assert db.get(Usuario, usuario_id) is None
    assert _acciones(db)[-1] == (
        auditoria.BORRAR_DATOS,
        usuario_id,
        usuario_id,
        {"cuenta": cuenta_id, "registros": 1},
    )
    assert [a[0] for a in _acciones(db)] == [auditoria.AUTORIZAR, auditoria.BORRAR_DATOS]  # se conservan
    _sin_datos_personales(db, OTRO, "Juana", "Tandil")


def test_la_terminal_registra_y_muestra_la_auditoria(motor, monkeypatch, capsys):
    migrar.preparar_base(motor)
    fabrica = sessionmaker(bind=motor, expire_on_commit=False)
    monkeypatch.setattr(terminal, "SessionLocal", fabrica)
    monkeypatch.setattr(terminal, "engine", motor)

    terminal.main(["auditoria"])
    assert "Todavía no hay acciones" in capsys.readouterr().out

    terminal.main(["usuarios", "autorizar", OTRO])
    terminal.main(["usuarios", "quitar", OTRO])
    capsys.readouterr()
    terminal.main(["auditoria", "--limite", "5"])
    salida = capsys.readouterr().out
    with fabrica() as db:
        u = db.scalar(select(Usuario).where(Usuario.telefono == OTRO))
    assert u is not None
    lineas = salida.strip().splitlines()
    assert "autorizar" in lineas[0] and "por terminal" in lineas[0] and f"sobre #{u.id}" in lineas[0]
    assert "quitar" in lineas[1]
    assert OTRO not in salida
