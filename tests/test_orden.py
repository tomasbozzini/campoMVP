"""Los mensajes de una misma persona se procesan de a uno y en orden."""

import threading

from fastapi.testclient import TestClient

from app import main
from app.infra.config import config
from app.infra.orden import FilaPorClave

ESPERA = 5  # segundos, por si algo se traba: el test falla en vez de colgarse


def test_misma_persona_de_a_uno_y_en_orden():
    fila = FilaPorClave()
    hechos: list[str] = []
    empezo, seguir = threading.Event(), threading.Event()

    def primero():
        empezo.set()
        assert seguir.wait(ESPERA)
        hechos.append("primero")

    hilo = threading.Thread(target=fila.ejecutar, args=("549111", primero))
    hilo.start()
    assert empezo.wait(ESPERA)
    # Llegan dos más mientras el primero sigue: quedan esperando, no arrancan.
    fila.ejecutar("549111", lambda: hechos.append("segundo"))
    fila.ejecutar("549111", lambda: hechos.append("tercero"))
    assert hechos == []

    seguir.set()
    hilo.join(ESPERA)
    assert hechos == ["primero", "segundo", "tercero"]
    assert fila.en_curso() == 0


def test_personas_distintas_no_se_esperan():
    fila = FilaPorClave()
    empezo, seguir = threading.Event(), threading.Event()

    def lento():
        empezo.set()
        assert seguir.wait(ESPERA)

    hilo = threading.Thread(target=fila.ejecutar, args=("549111", lento))
    hilo.start()
    assert empezo.wait(ESPERA)
    hechos: list[str] = []
    fila.ejecutar("549222", lambda: hechos.append("otra persona"))  # no espera al lento
    assert hechos == ["otra persona"]
    seguir.set()
    hilo.join(ESPERA)


def test_un_error_no_frena_la_fila():
    fila = FilaPorClave()
    hechos: list[str] = []

    def falla():
        raise ValueError("algo salió mal")

    empezo, seguir = threading.Event(), threading.Event()

    def primero():
        empezo.set()
        assert seguir.wait(ESPERA)

    hilo = threading.Thread(target=fila.ejecutar, args=("549111", primero))
    hilo.start()
    assert empezo.wait(ESPERA)
    fila.ejecutar("549111", falla)
    fila.ejecutar("549111", lambda: hechos.append("sigue"))
    seguir.set()
    hilo.join(ESPERA)
    assert hechos == ["sigue"]


def test_el_webhook_procesa_en_el_orden_en_que_se_escribieron(servidor, monkeypatch):
    """Meta puede mandar varios mensajes juntos y no siempre ordenados."""
    monkeypatch.setattr(config, "admin_telefonos", {"5491100000001"})

    def mensaje(wamid: str, texto: str, timestamp: str) -> dict:
        return {"from": "5491100000001", "id": wamid, "timestamp": timestamp, "type": "text", "text": {"body": texto}}

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                mensaje("wamid.2", "privacidad", "1760000002"),
                                mensaje("wamid.1", "ayuda", "1760000001"),
                            ]
                        }
                    }
                ]
            }
        ]
    }
    with TestClient(main.app) as c:
        c.post("/webhook", json=payload)
    assert ["TU ASISTENTE" in t for _, t in servidor] == [True, False]
    assert "TUS DATOS" in servidor[1][1]
