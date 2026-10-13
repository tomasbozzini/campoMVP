"""Comandos de terminal: python -m app <comando>."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import terminal
from app.infra.db import Base
from app.nucleo import usuarios


@pytest.fixture
def sesiones(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/terminal.db")
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(terminal, "SessionLocal", fabrica)
    monkeypatch.setattr(terminal, "crear_tablas", lambda: None)
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
