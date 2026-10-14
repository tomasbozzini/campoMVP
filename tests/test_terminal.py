"""Comandos de terminal: python -m app <comando>."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from app import terminal
from app.infra import db, migrar
from app.infra.db import Base
from app.nucleo import usuarios


@pytest.fixture
def sesiones(monkeypatch, motor):
    migrar.preparar_base(motor)
    fabrica = sessionmaker(bind=motor, expire_on_commit=False)
    monkeypatch.setattr(terminal, "SessionLocal", fabrica)
    monkeypatch.setattr(terminal, "engine", motor)
    return fabrica


def test_usuarios_autorizar_lista_y_quitar(sesiones, capsys):
    terminal.main(["usuarios", "autorizar", "+54", "9", "249", "412-3456"])
    terminal.main(["usuarios", "lista"])
    assert "5492494123456" in capsys.readouterr().out
    with sesiones() as db:
        assert [u.telefono for u in usuarios.autorizados(db)] == ["5492494123456"]

    terminal.main(["usuarios", "quitar", "5492494123456"])
    assert "acceso quitado" in capsys.readouterr().out
    with sesiones() as db:
        assert usuarios.autorizados(db) == []


def test_numero_invalido(sesiones):
    with pytest.raises(SystemExit, match="Número inválido"):
        terminal.main(["usuarios", "autorizar", "123"])


def test_ver_precios_y_senasa_sin_datos(sesiones, capsys):
    terminal.main(["precios", "ver", "soja"])
    terminal.main(["senasa", "ver", "ivermectina"])
    salida = capsys.readouterr().out
    assert "No tengo precios cargados" in salida
    assert "Todavía no tengo cargado el registro" in salida


def test_comando_desconocido():
    with pytest.raises(SystemExit):
        terminal.main(["inventado"])


def test_db_migrar_con_una_base_vieja_distinta_explica_sin_traceback(motor, monkeypatch, capsys):
    Base.metadata.create_all(motor)
    with motor.begin() as c:
        c.execute(text("drop index ix_eventos_mensaje_id"))
        c.execute(text("alter table eventos drop column mensaje_id"))
    monkeypatch.setattr(terminal, "engine", motor)

    with pytest.raises(SystemExit) as salida:
        terminal.main(["db", "migrar"])
    mensaje = str(salida.value.code)
    assert "mensaje_id" in mensaje and "No se tocó nada" in mensaje
    assert "Traceback" not in mensaje + capsys.readouterr().err


@pytest.mark.parametrize("comando", [["usuarios", "lista"], ["precios", "ver", "soja"], ["chat"]])
def test_los_comandos_no_migran_y_avisan_si_falta(motor, monkeypatch, comando):
    """Solo `db migrar` cambia la base; el resto avisa y no hace nada."""
    monkeypatch.setattr(terminal, "engine", motor)
    monkeypatch.setattr(terminal, "SessionLocal", sessionmaker(bind=motor))
    monkeypatch.setattr(db, "engine", motor)

    with pytest.raises(SystemExit) as salida:
        terminal.main(comando)
    assert "python -m app db migrar" in str(salida.value.code)
    assert inspect(motor).get_table_names() == []
