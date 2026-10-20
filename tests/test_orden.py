"""Los mensajes de una misma persona se procesan de a uno y en orden."""

import threading
from collections import defaultdict
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app import main
from app.infra.config import config
from app.infra.marca import NOMBRE
from app.infra.orden import FilaPorClave
from app.nucleo import pipeline

ESPERA = 5  # segundos, por si algo se traba: el test falla en vez de colgarse


# Los trabajos no hacen assert: la fila registra y sigue ante cualquier excepción, así que
# un assert adentro no haría fallar el test. Anotan lo que pasó y se verifica afuera.


def _frenado(nombre: str, hechos: list[str]) -> tuple[threading.Event, threading.Event, Callable[[], None]]:
    """Un trabajo que avisa cuando empieza y no termina hasta que se lo suelta."""
    empezo, seguir = threading.Event(), threading.Event()

    def trabajo() -> None:
        empezo.set()
        hechos.append(nombre if seguir.wait(ESPERA) else f"{nombre}: nadie lo soltó")

    return empezo, seguir, trabajo


def test_misma_persona_de_a_uno_y_en_orden():
    fila = FilaPorClave()
    hechos: list[str] = []
    empezo, seguir, primero = _frenado("primero", hechos)

    fila.encolar("549111", primero)
    assert empezo.wait(ESPERA)
    # Llegan dos más mientras el primero sigue: quedan esperando, no arrancan.
    fila.encolar("549111", lambda: hechos.append("segundo"))
    fila.encolar("549111", lambda: hechos.append("tercero"))
    assert hechos == []

    seguir.set()
    assert fila.esperar(ESPERA)
    assert hechos == ["primero", "segundo", "tercero"]
    assert fila.en_curso() == 0


def test_encolar_no_espera_a_que_se_procese():
    fila = FilaPorClave()
    hechos: list[str] = []
    empezo, seguir, lento = _frenado("lento", hechos)
    fila.encolar("549111", lento)  # vuelve enseguida aunque el trabajo siga
    assert empezo.wait(ESPERA)
    assert fila.en_curso() == 1
    seguir.set()
    assert fila.esperar(ESPERA)


def test_personas_distintas_no_se_esperan():
    fila = FilaPorClave()
    hechos: list[str] = []
    empezo, seguir, lento = _frenado("lento", hechos)
    fila.encolar("549111", lento)
    assert empezo.wait(ESPERA)

    otra_persona = threading.Event()
    fila.encolar("549222", otra_persona.set)
    assert otra_persona.wait(ESPERA)  # corrió mientras el lento seguía
    assert hechos == []

    seguir.set()
    assert fila.esperar(ESPERA)
    assert hechos == ["lento"]


def test_un_error_no_frena_la_fila():
    fila = FilaPorClave()
    hechos: list[str] = []
    empezo, seguir, primero = _frenado("primero", hechos)

    def falla() -> None:
        raise ValueError("algo salió mal")

    fila.encolar("549111", primero)
    assert empezo.wait(ESPERA)
    fila.encolar("549111", falla)
    fila.encolar("549111", lambda: hechos.append("sigue"))
    seguir.set()
    assert fila.esperar(ESPERA)
    assert hechos == ["primero", "sigue"]


class Grave(BaseException):
    """Como un KeyboardInterrupt o un SystemExit: no lo ataja un `except Exception`."""


def test_una_excepcion_grave_no_traba_a_la_persona():
    fila = FilaPorClave()
    hechos: list[str] = []
    empezo, seguir, primero = _frenado("primero", hechos)

    def grave() -> None:
        raise Grave

    fila.encolar("549111", primero)
    assert empezo.wait(ESPERA)
    fila.encolar("549111", grave)
    fila.encolar("549111", lambda: hechos.append("lo que seguía"))
    seguir.set()
    assert fila.esperar(ESPERA)
    assert hechos == ["primero", "lo que seguía"]

    fila.encolar("549111", lambda: hechos.append("un mensaje nuevo"))
    assert fila.esperar(ESPERA)
    assert hechos == ["primero", "lo que seguía", "un mensaje nuevo"]
    assert fila.en_curso() == 0


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
    assert [NOMBRE.upper() in t for _, t in servidor] == [True, False]
    assert "TUS DATOS" in servidor[1][1]


X, Y = "5491100000001", "5491100000002"


def _webhook(*mensajes: tuple[str, str, int]) -> dict:
    """Un webhook de Meta con mensajes de texto (teléfono, texto, timestamp); el texto hace de id."""
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": tel, "id": f"wamid.{texto}", "timestamp": str(ts), "type": "text", "text": {"body": texto}}
        for tel, texto, ts in mensajes
    ]}}]}]}  # fmt: skip


class PipelineFalso:
    """Reemplaza al pipeline: anota en qué orden empieza cada mensaje y puede frenar uno."""

    def __init__(self) -> None:
        self.orden: list[str] = []
        self.empezo: dict[str, threading.Event] = defaultdict(threading.Event)
        self.listo: dict[str, threading.Event] = defaultdict(threading.Event)
        self.frenados: dict[str, threading.Event] = {}

    def frenar(self, texto: str) -> threading.Event:
        """El mensaje queda procesándose hasta que se active el evento que devuelve."""
        self.frenados[texto] = threading.Event()
        return self.frenados[texto]

    def __call__(self, _db, _telefono, texto: str, nombre=None, hoy=None, audio=False) -> pipeline.Respuesta:
        self.orden.append(texto)
        self.empezo[texto].set()
        if texto in self.frenados:
            self.frenados[texto].wait(ESPERA)
        self.listo[texto].set()
        return pipeline.Respuesta(texto)


@pytest.fixture
def procesar(servidor, monkeypatch):
    falso = PipelineFalso()
    monkeypatch.setattr(pipeline, "atender", falso)
    return falso


def _en_paralelo(cliente: TestClient, payload: dict) -> threading.Thread:
    hilo = threading.Thread(target=cliente.post, args=("/webhook",), kwargs={"json": payload})
    hilo.start()
    return hilo


def test_un_lote_no_se_intercala_con_el_webhook_siguiente(procesar):
    """Meta manda [a1, a2] juntos y b1 en otro webhook mientras se procesa a1: va a1, a2, b1."""
    seguir = procesar.frenar("a1")
    with TestClient(main.app) as c:
        primero = _en_paralelo(c, _webhook((X, "a1", 1), (X, "a2", 2)))
        assert procesar.empezo["a1"].wait(ESPERA)
        c.post("/webhook", json=_webhook((X, "b1", 3)))
        seguir.set()
        primero.join(ESPERA)
    assert procesar.orden == ["a1", "a2", "b1"]


def test_en_un_lote_una_persona_no_espera_a_otra(procesar):
    """En [X:a1, Y:y1], y1 no espera a que termine a1; y el y2 que llega después va detrás de y1."""
    seguir = procesar.frenar("a1")
    with TestClient(main.app) as c:
        primero = _en_paralelo(c, _webhook((X, "a1", 1), (Y, "y1", 2)))
        assert procesar.empezo["a1"].wait(ESPERA)
        c.post("/webhook", json=_webhook((Y, "y2", 3)))
        assert procesar.listo["y2"].wait(ESPERA)
        orden_con_a1_frenado = list(procesar.orden)
        seguir.set()
        primero.join(ESPERA)
    assert orden_con_a1_frenado == ["a1", "y1", "y2"]
