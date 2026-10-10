import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(main, "crear_tablas", lambda: None)
    monkeypatch.setattr(config, "WA_VERIFY_TOKEN", "mi-token")
    monkeypatch.setattr(config, "META_APP_SECRET", "")
    enviados = []
    monkeypatch.setattr(main.whatsapp, "enviar_texto", lambda tel, txt: enviados.append((tel, txt)))
    with TestClient(main.app) as c:
        c.enviados = enviados
        yield c


def test_verificacion(cliente):
    params = {"hub.mode": "subscribe", "hub.verify_token": "mi-token", "hub.challenge": "123"}
    assert cliente.get("/webhook", params=params).text == "123"
    params["hub.verify_token"] = "otro"
    assert cliente.get("/webhook", params=params).status_code == 403


def _payload(wamid, texto):
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "5491100000001", "profile": {"name": "Juan"}}],
        "messages": [{"from": "5491100000001", "id": wamid, "type": "text", "text": {"body": texto}}],
    }}]}]}


def test_mensaje_de_texto_y_reintento_duplicado(cliente):
    cliente.post("/webhook", json=_payload("wamid.1", "crear campo El Ombú"))
    cliente.post("/webhook", json=_payload("wamid.1", "crear campo El Ombú"))  # reintento de Meta
    assert len(cliente.enviados) == 1
    assert "El Ombú" in cliente.enviados[0][1]


def test_audio_de_numero_sin_campo_no_se_transcribe(cliente, monkeypatch):
    def no_llamar(*_):
        raise AssertionError("no debería descargar ni transcribir")

    monkeypatch.setattr(main.whatsapp, "descargar_media", no_llamar)
    monkeypatch.setattr(main.llm, "transcribir", no_llamar)
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "5491100000099", "id": "wamid.a1", "type": "audio", "audio": {"id": "media1"}},
    ]}}]}]}
    cliente.post("/webhook", json=payload)
    assert "crear campo" in cliente.enviados[-1][1]
