"""El registro de acciones se carga una sola vez, al arrancar."""

import contextlib
import threading

import pytest
from fastapi.testclient import TestClient

from app import main, modulos, terminal
from app.nucleo import acciones


@pytest.fixture
def registro_vacio(monkeypatch):
    """Como recién arrancado el proceso: ningún módulo cargado."""
    monkeypatch.setattr(acciones, "_registro", {})
    monkeypatch.setattr(modulos, "_partes", {})
    monkeypatch.setattr(modulos, "_cargados", False)


def test_dos_cargas_a_la_vez_no_fallan(registro_vacio, monkeypatch):
    """Dos mensajes que llegan juntos apenas arranca el bot: el segundo fallaba con "ya está registrada"."""
    registrar = acciones.registrar
    juntos = threading.Barrier(2, timeout=1)

    def registrar_cuando_lleguen_los_dos(*lista):
        # Los dos hilos registran a la vez, si el código los deja.
        with contextlib.suppress(threading.BrokenBarrierError):
            juntos.wait()
        registrar(*lista)

    monkeypatch.setattr(acciones, "registrar", registrar_cuando_lleguen_los_dos)
    errores: list[BaseException] = []

    def cargar():
        try:
            modulos.cargar()
        except Exception as e:
            errores.append(e)

    hilos = [threading.Thread(target=cargar) for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(5)
    assert errores == []
    assert "registrar" in acciones.intenciones()


def test_el_servidor_carga_los_modulos_al_arrancar(registro_vacio, servidor):
    with TestClient(main.app):
        assert "registrar" in acciones.intenciones()


def test_la_terminal_carga_los_modulos_al_arrancar(registro_vacio, motor, monkeypatch):
    monkeypatch.setattr(terminal, "engine", motor)
    terminal.main(["db", "estado"])
    assert "registrar" in acciones.intenciones()
