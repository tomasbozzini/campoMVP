import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import webhook
from app.canales import whatsapp
from app.ia import interprete
from app.infra.config import config


@pytest.fixture
def cliente(servidor, monkeypatch):
    monkeypatch.setattr(config, "wa_verify_token", "mi-token")
    monkeypatch.setattr(config, "meta_app_secret", "")
    with TestClient(main.app) as c:
        c.enviados = servidor
        # Los mensajes se procesan aparte: esto espera a que terminen.
        c.esperar = lambda: webhook.fila.esperar(5)
        yield c


def test_verificacion(cliente):
    params = {"hub.mode": "subscribe", "hub.verify_token": "mi-token", "hub.challenge": "123"}
    assert cliente.get("/webhook", params=params).text == "123"
    params["hub.verify_token"] = "otro"
    assert cliente.get("/webhook", params=params).status_code == 403


def _payload(wamid, texto):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": "5491100000001", "profile": {"name": "Juan"}}],
                            "messages": [
                                {"from": "5491100000001", "id": wamid, "type": "text", "text": {"body": texto}}
                            ],
                        }
                    }
                ]
            }
        ]
    }


def test_mensaje_de_texto_y_reintento_duplicado(cliente, monkeypatch):
    monkeypatch.setattr(config, "admin_telefonos", {"5491100000001"})
    cliente.post("/webhook", json=_payload("wamid.1", "ayuda"))
    cliente.post("/webhook", json=_payload("wamid.1", "ayuda"))  # reintento de Meta
    assert cliente.esperar()
    assert len(cliente.enviados) == 1
    assert "CAMPOBOT" in cliente.enviados[0][1]


def test_audio_de_numero_sin_acceso_no_se_transcribe(cliente, monkeypatch):
    def no_llamar(*_):
        raise AssertionError("no debería descargar ni transcribir")

    monkeypatch.setattr(whatsapp, "descargar_media", no_llamar)
    monkeypatch.setattr(interprete, "transcribir", no_llamar)
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": "5491100000099", "id": "wamid.a1", "type": "audio", "audio": {"id": "media1"}},
                            ]
                        }
                    }
                ]
            }
        ]
    }
    cliente.post("/webhook", json=payload)
    assert cliente.esperar()
    assert "no tiene acceso" in cliente.enviados[-1][1]


def test_politica_de_privacidad(cliente, monkeypatch):
    monkeypatch.setattr(config, "privacidad_responsable", "Campo <Bot>")
    monkeypatch.setattr(config, "privacidad_contacto", "datos@ejemplo.com")
    r = cliente.get("/privacidad")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "Campo &lt;Bot&gt;" in r.text and "datos@ejemplo.com" in r.text
    assert "Ley 25.326" in r.text and "borrar mis datos" in r.text


@pytest.mark.parametrize("timestamp", ["ayer", "17.6e8x", {"segundos": 1}, None])
def test_un_timestamp_mal_formado_no_tira_abajo_el_webhook(cliente, monkeypatch, timestamp):
    monkeypatch.setattr(config, "admin_telefonos", {"5491100000001"})
    payload = _payload("wamid.t1", "ayuda")
    mensajes = payload["entry"][0]["changes"][0]["value"]["messages"]
    mensajes[0]["timestamp"] = timestamp
    mensajes.append(
        {
            "from": "5491100000001",
            "id": "wamid.t2",
            "timestamp": "1760000000",
            "type": "text",
            "text": {"body": "privacidad"},
        }
    )
    assert cliente.post("/webhook", json=payload).status_code == 200
    assert cliente.esperar()
    assert len(cliente.enviados) == 2
