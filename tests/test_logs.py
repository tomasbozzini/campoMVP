"""Logs sin datos personales: ni el teléfono, ni el texto de los mensajes, ni secretos."""

import logging
import logging.config
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from groq import BadRequestError
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker
from uvicorn.config import LOGGING_CONFIG

from app import main
from app.ia import proveedor
from app.ia.proveedor_groq import ProveedorGroq
from app.infra.config import config
from app.infra.logs import configurar_logs, enmascarar
from app.infra.modelos import MensajeProcesado
from app.nucleo import charla

TELEFONO = "5492494123456"
TEXTO = "Vacuné 20 vaquillonas de Juan Pérez en La Esperanza"
# Un wamid real lleva el teléfono en base64 ("NTQ5MjQ5NDEyMzQ1Ng" es 5492494123456).
WAMID = "wamid.HBgNNTQ5MjQ5NDEyMzQ1NhUCABIYFjNFQjBGNkQ2QkI3QzE5RkM5MEUzNjEA"


@pytest.fixture
def logs(capsys):
    """Los logs tal como salen en la terminal del servidor (con los handlers del bot)."""
    configurar_logs()

    def leer() -> str:
        salida: str = capsys.readouterr().err
        return salida

    return leer


def _webhook(texto: str = TEXTO, wamid: str = WAMID) -> dict:
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": TELEFONO, "profile": {"name": "Juan Pérez"}}],
        "messages": [{"from": TELEFONO, "id": wamid, "timestamp": "1760000000", "type": "text", "text": {"body": texto}}],
    }}]}]}  # fmt: skip


def _groq_que_falla() -> ProveedorGroq:
    """Groq devuelve 400 con la generación fallida, que repite el texto de la persona."""
    cuerpo = {"error": {"message": "json_validate_failed", "failed_generation": f'{{"texto": "{TEXTO}"}}'}}
    respuesta = httpx.Response(400, json=cuerpo, request=httpx.Request("POST", "https://api.groq.com/x"))

    def fallar(**_kwargs):
        raise BadRequestError(f"Error code: 400 - {cuerpo}", response=respuesta, body=cuerpo)

    groq = ProveedorGroq("clave", "modelo", "whisper")
    groq._cliente = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fallar)))  # type: ignore[assignment]
    return groq


def _sin_datos_personales(salida: str) -> None:
    for dato in (TELEFONO, TEXTO, "Juan Pérez", WAMID, WAMID.removeprefix("wamid.")):
        assert dato not in salida, f"{dato!r} aparece en los logs:\n{salida}"


def test_un_error_de_groq_no_lleva_el_texto_ni_el_telefono_al_log(servidor, monkeypatch, logs):
    monkeypatch.setattr(config, "admin_telefonos", {TELEFONO})
    proveedor.usar(_groq_que_falla())
    try:
        with TestClient(main.app) as c:
            c.post("/webhook", json=_webhook())
    finally:
        proveedor.usar(None)
    salida = logs()
    assert "BadRequestError" in salida and "400" in salida  # el tipo y el código sí
    assert "no pude procesar" in servidor[0][1]
    _sin_datos_personales(salida)


def test_un_error_de_la_base_no_muestra_los_parametros(servidor, monkeypatch, logs):
    """Un error de la base en medio del mensaje: el log no muestra lo que se iba a guardar."""
    monkeypatch.setattr(config, "admin_telefonos", {TELEFONO})

    def guardar_roto(cuaderno, texto_usuario, _respuesta):
        cuaderno.db.execute(
            text("insert into tabla_inexistente values (:t, :tel)"), {"t": texto_usuario, "tel": TELEFONO}
        )

    monkeypatch.setattr(charla, "guardar", guardar_roto)
    with TestClient(main.app) as c:
        c.post("/webhook", json=_webhook("ayuda"))
    salida = logs()
    assert "tabla_inexistente" in salida  # el error se ve, los datos no
    assert "algo falló" in servidor[0][1]
    _sin_datos_personales(salida)


def test_los_logs_de_uvicorn_pasan_por_el_enmascarado(logs):
    logging.config.dictConfig(LOGGING_CONFIG)  # como lo deja uvicorn antes de cargar la app
    configurar_logs()  # lo que hace app/main.py al importarse
    logging.getLogger("uvicorn.error").error("Fallo atendiendo a %s", TELEFONO)
    assert TELEFONO not in logs()


def test_el_access_log_no_muestra_el_token_de_verificacion(logs):
    logging.config.dictConfig(LOGGING_CONFIG)
    configurar_logs()
    ruta = "/webhook?hub.mode=subscribe&hub.verify_token=TOKEN-SECRETO&hub.challenge=123"
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "GET", ruta, "1.1", 200)
    salida = logs()
    assert '"GET /webhook HTTP/1.1" 200' in salida
    assert "TOKEN-SECRETO" not in salida


def test_el_enmascarado_cubre_numeros_de_hasta_15_digitos():
    assert enmascarar("de 123456789012345 a") == "de 123*********345 a"  # 15 dígitos (E.164)
    assert enmascarar("1234567890123456") == "1234567890123456"  # 16 ya no es un teléfono


def test_los_ids_de_mensajes_se_borran_a_los_7_dias(servidor, monkeypatch, motor):
    """Sirven para descartar los reintentos de Meta (que reintenta hasta 7 días) y llevan el teléfono."""
    monkeypatch.setattr(config, "admin_telefonos", {TELEFONO})
    ahora = datetime.now(UTC)
    with sessionmaker(bind=motor)() as db:
        db.add_all(
            [
                MensajeProcesado(wamid="wamid.viejo", creado=ahora - timedelta(days=8)),
                MensajeProcesado(wamid="wamid.reciente", creado=ahora - timedelta(days=6)),
            ]
        )
        db.commit()
    with TestClient(main.app) as c:
        c.post("/webhook", json=_webhook("ayuda", wamid="wamid.nuevo"))
    with sessionmaker(bind=motor)() as db:
        assert sorted(db.scalars(select(MensajeProcesado.wamid))) == ["wamid.nuevo", "wamid.reciente"]


def test_el_texto_del_mensaje_no_se_loguea_en_el_camino_normal(servidor, monkeypatch, logs):
    monkeypatch.setattr(config, "admin_telefonos", {TELEFONO})
    with TestClient(main.app) as c:
        c.post("/webhook", json=_webhook("ayuda"))
        c.post("/webhook", json=_webhook("ayuda"))  # reintento de Meta
    assert "CAMPOBOT" in servidor[0][1]
    _sin_datos_personales(logs())
