"""Firma del webhook, arranque en producción, configuración y logs sin teléfonos."""

import hashlib
import hmac
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import main
from app.infra.config import Configuracion, config
from app.infra.logs import FormateadorSinTelefonos, enmascarar

SECRETO = "secreto-de-meta"
ADMIN = "5491100000001"


def _produccion(monkeypatch):
    for campo, valor in {
        "entorno": "produccion",
        "meta_app_secret": SECRETO,
        "wa_verify_token": "mi-token",
        "wa_token": "token",
        "wa_phone_number_id": "123",
        "groq_api_key": "clave",
        "admin_telefonos": {ADMIN},
    }.items():
        monkeypatch.setattr(config, campo, valor)


def _cuerpo(wamid: str = "wamid.s1") -> bytes:
    return json.dumps({"entry": [{"changes": [{"value": {
        "messages": [{"from": ADMIN, "id": wamid, "type": "text", "text": {"body": "ayuda"}}],
    }}]}]}).encode()  # fmt: skip


def _firma(cuerpo: bytes, secreto: str = SECRETO) -> str:
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def test_produccion_rechaza_el_webhook_sin_firma(servidor, monkeypatch):
    _produccion(monkeypatch)
    with TestClient(main.app) as c:
        r = c.post("/webhook", content=_cuerpo(), headers={"Content-Type": "application/json"})
    assert r.status_code == 401
    assert servidor == []


def test_produccion_rechaza_una_firma_incorrecta(servidor, monkeypatch):
    _produccion(monkeypatch)
    cuerpo = _cuerpo()
    with TestClient(main.app) as c:
        r = c.post("/webhook", content=cuerpo, headers={"X-Hub-Signature-256": _firma(cuerpo, "otro")})
    assert r.status_code == 401
    assert servidor == []


def test_produccion_acepta_la_firma_valida(servidor, monkeypatch):
    _produccion(monkeypatch)
    cuerpo = _cuerpo()
    with TestClient(main.app) as c:
        r = c.post("/webhook", content=cuerpo, headers={"X-Hub-Signature-256": _firma(cuerpo)})
    assert r.status_code == 200
    assert len(servidor) == 1 and "TU ASISTENTE" in servidor[0][1]


@pytest.mark.parametrize(
    "variable", ["meta_app_secret", "wa_verify_token", "wa_token", "wa_phone_number_id", "groq_api_key"]
)
def test_produccion_no_arranca_si_falta_una_variable(servidor, monkeypatch, variable):
    _produccion(monkeypatch)
    monkeypatch.setattr(config, variable, "")
    with pytest.raises(RuntimeError, match=variable.upper()), TestClient(main.app):
        pass


def test_desarrollo_con_secreto_tambien_valida_la_firma(servidor, monkeypatch):
    """Probando con ngrok y mensajes reales de Meta, la firma se valida igual."""
    monkeypatch.setattr(config, "meta_app_secret", SECRETO)
    monkeypatch.setattr(config, "admin_telefonos", {ADMIN})
    cuerpo = _cuerpo()
    with TestClient(main.app) as c:
        assert c.post("/webhook", content=cuerpo).status_code == 401
        assert c.post("/webhook", content=cuerpo, headers={"X-Hub-Signature-256": _firma(cuerpo)}).status_code == 200
    assert len(servidor) == 1


def test_desarrollo_sin_secreto_arranca_y_no_valida(servidor, monkeypatch):
    monkeypatch.setattr(config, "admin_telefonos", {ADMIN})
    with TestClient(main.app) as c:
        assert c.post("/webhook", content=_cuerpo()).status_code == 200
    assert len(servidor) == 1


def test_por_defecto_el_entorno_es_produccion(monkeypatch):
    monkeypatch.delenv("ENTORNO", raising=False)
    assert Configuracion(_env_file=None).entorno == "produccion"


def test_configuracion_desde_variables_de_entorno(monkeypatch):
    monkeypatch.setenv("ENTORNO", "Desarrollo")
    monkeypatch.setenv("ADMIN_TELEFONOS", " 5492494000001, 5492494000002 ,")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:c@host/base")
    monkeypatch.setenv("WA_AR_QUITAR_9", "sí")
    monkeypatch.setenv("LIMITE_DIARIO_IA", "15")
    c = Configuracion(_env_file=None)
    assert c.entorno == "desarrollo"
    assert c.admin_telefonos == {"5492494000001", "5492494000002"}
    assert c.database_url == "postgresql://u:c@host/base"
    assert c.wa_ar_quitar_9 is True
    assert c.limite_diario_ia == 15


def test_configuracion_invalida_falla_con_el_nombre_de_la_variable(monkeypatch):
    monkeypatch.setenv("LIMITE_DIARIO_IA", "muchos")
    with pytest.raises(ValueError, match="limite_diario_ia"):
        Configuracion(_env_file=None)


def test_los_logs_enmascaran_los_telefonos():
    assert enmascarar("Error enviando a 5492494123456: 400") == "Error enviando a 549*******456: 400"
    assert enmascarar("542494123456 y +54 9 249") == "542******456 y +54 9 249"
    assert enmascarar("lote 3, 20 vacas, 2026-10-09") == "lote 3, 20 vacas, 2026-10-09"

    registro = logging.LogRecord("x", logging.ERROR, __file__, 1, "Usuario %s falló", ("5492494123456",), None)
    texto = FormateadorSinTelefonos("%(message)s").format(registro)
    assert "5492494123456" not in texto and "549*******456" in texto


def test_una_variable_vacia_en_el_env_usa_el_valor_por_defecto(tmp_path):
    """El .env.example trae GROQ_MODELO= vacío: no puede pisar el modelo por defecto con ""."""
    env = tmp_path / ".env"
    env.write_text("GROQ_MODELO=\nGROQ_MODELO_AUDIO=\nLIMITE_DIARIO_IA=\n", encoding="utf-8")
    c = Configuracion(_env_file=env)
    defecto = Configuracion(_env_file=None)
    assert c.groq_modelo == defecto.groq_modelo != ""
    assert c.groq_modelo_audio == defecto.groq_modelo_audio
    assert c.limite_diario_ia == defecto.limite_diario_ia

