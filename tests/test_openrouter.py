"""OpenRouter como IA principal, Groq de respaldo, y la IA saturada."""

import json
import time
from collections.abc import Callable
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from groq import APITimeoutError, BadRequestError, RateLimitError

from app import main
from app.api import webhook
from app.canales import whatsapp
from app.ia import proveedor
from app.ia.proveedor import ConRespaldo, ErrorIA, IASaturada
from app.ia.proveedor_groq import ProveedorGroq
from app.ia.proveedor_openrouter import URL, ProveedorOpenRouter
from app.infra.config import Configuracion, config
from app.infra.logs import configurar_logs
from app.nucleo import pipeline
from tests.ayudas import con_perfil, con_perfil_en

HOY = date(2026, 10, 16)
TELEFONO = "5492494123456"
TEXTO = "Vacuné 20 vaquillonas de Juan Pérez en La Esperanza"


def _respuesta_ok(contenido: str = '{"acciones": [{"intencion": "saludo"}]}') -> dict:
    return {
        "provider": "Cerebras",
        "choices": [{"message": {"content": contenido}}],
        "usage": {
            "prompt_tokens": 4712,
            "completion_tokens": 95,
            "completion_tokens_details": {"reasoning_tokens": 60},
            "cost": 0.00031,
        },
    }


def _openrouter(manejar: Callable[[httpx.Request], httpx.Response]) -> tuple[ProveedorOpenRouter, list[httpx.Request]]:
    pedidos: list[httpx.Request] = []

    def transporte(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return manejar(pedido)

    cliente = httpx.Client(transport=httpx.MockTransport(transporte))
    return ProveedorOpenRouter("clave-or", "openai/gpt-oss-120b", "low", cliente), pedidos


# --- El pedido y la respuesta -------------------------------------------------------------


def test_pide_solo_proveedores_que_no_guardan_datos_y_aceptan_el_json():
    openrouter, pedidos = _openrouter(lambda _p: httpx.Response(200, json=_respuesta_ok()))
    assert openrouter.completar_json("sis", "msj") == {"acciones": [{"intencion": "saludo"}]}

    pedido = pedidos[0]
    assert str(pedido.url) == URL and pedido.headers["Authorization"] == "Bearer clave-or"
    cuerpo = json.loads(pedido.content)
    assert cuerpo["model"] == "openai/gpt-oss-120b"
    assert cuerpo["messages"] == [{"role": "system", "content": "sis"}, {"role": "user", "content": "msj"}]
    assert cuerpo["response_format"] == {"type": "json_object"}
    assert cuerpo["provider"] == {
        "zdr": True,
        "data_collection": "deny",
        "require_parameters": True,
        "order": ["cerebras", "groq"],
        "allow_fallbacks": True,
    }
    assert cuerpo["reasoning"] == {"effort": "low"}


def test_anota_quien_respondio_los_tokens_y_el_costo():
    openrouter, _ = _openrouter(lambda _p: httpx.Response(200, json=_respuesta_ok()))
    with proveedor.medir() as usos:
        openrouter.completar_json("sis", "msj")
    [uso] = usos
    assert (uso.proveedor, uso.servidor) == ("openrouter", "Cerebras")
    assert (uso.tokens_entrada, uso.tokens_salida, uso.tokens_razonamiento) == (4712, 95, 60)
    assert uso.costo_usd == pytest.approx(0.00031)


@pytest.mark.parametrize("codigo", [402, 408, 429, 502, 503])
def test_sin_saldo_limite_o_sin_servidores_es_ia_saturada(codigo):
    cuerpo = {"error": {"code": codigo, "message": f"falló con {TEXTO}"}}
    openrouter, _ = _openrouter(lambda _p: httpx.Response(codigo, json=cuerpo))
    with pytest.raises(IASaturada) as error:
        openrouter.completar_json("sis", "msj")
    assert str(error.value) == f"OpenRouter {codigo}"  # el código, sin el cuerpo


def test_sin_respuesta_es_ia_saturada():
    def colgado(pedido):
        raise httpx.ReadTimeout("timeout", request=pedido)

    openrouter, _ = _openrouter(colgado)
    with pytest.raises(IASaturada, match="ReadTimeout"):
        openrouter.completar_json("sis", "msj")


class Goteo(httpx.SyncByteStream):
    """Como OpenRouter mientras procesa: espacios cada tanto, y la respuesta al final."""

    def __iter__(self):
        for _ in range(5):
            time.sleep(0.03)
            yield b" "
        yield json.dumps(_respuesta_ok()).encode()


def test_los_espacios_para_mantener_viva_la_conexion_no_estiran_la_espera():
    cliente = httpx.Client(transport=httpx.MockTransport(lambda _p: httpx.Response(200, stream=Goteo())))
    lento = ProveedorOpenRouter("clave-or", "openai/gpt-oss-120b", "low", cliente, espera=0.05)
    with pytest.raises(IASaturada, match=r"sin respuesta en 0.05 s"):
        lento.completar_json("sis", "msj")
    a_tiempo = ProveedorOpenRouter("clave-or", "openai/gpt-oss-120b", "low", cliente, espera=5)
    assert a_tiempo.completar_json("sis", "msj") == {"acciones": [{"intencion": "saludo"}]}


@pytest.mark.parametrize(
    "respuesta",
    [
        httpx.Response(400, json={"error": {"code": 400, "message": TEXTO}}),
        httpx.Response(200, json=_respuesta_ok("no es json")),
        httpx.Response(200, json=_respuesta_ok("")),
        httpx.Response(200, text="<html>"),
    ],
)
def test_un_pedido_o_una_respuesta_mala_es_un_error_comun(respuesta):
    openrouter, _ = _openrouter(lambda _p: respuesta)
    with pytest.raises(ErrorIA) as error:
        openrouter.completar_json("sis", "msj")
    assert not isinstance(error.value, IASaturada) and TEXTO not in str(error.value)


# --- Groq: qué es estar saturada ----------------------------------------------------------


def _groq_que_falla(error: Exception) -> ProveedorGroq:
    def fallar(**_kwargs):
        raise error

    groq = ProveedorGroq("clave", "modelo", "whisper")
    groq._cliente = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fallar)))  # type: ignore[assignment]
    return groq


def _error_groq(clase, codigo):
    respuesta = httpx.Response(codigo, request=httpx.Request("POST", "https://api.groq.com/x"))
    return clase(f"Error code: {codigo}", response=respuesta, body=None)


def test_groq_con_limite_o_sin_respuesta_esta_saturada():
    with pytest.raises(IASaturada, match="RateLimitError 429"):
        _groq_que_falla(_error_groq(RateLimitError, 429)).completar_json("sis", "msj")
    timeout = APITimeoutError(request=httpx.Request("POST", "https://api.groq.com/x"))
    with pytest.raises(IASaturada, match="APITimeoutError"):
        _groq_que_falla(timeout).completar_json("sis", "msj")
    with pytest.raises(ErrorIA) as error:
        _groq_que_falla(_error_groq(BadRequestError, 400)).completar_json("sis", "msj")
    assert not isinstance(error.value, IASaturada)


# --- Principal y respaldo -----------------------------------------------------------------


class Falso:
    def __init__(self, respuesta: object = None, error: Exception | None = None) -> None:
        self.respuesta, self.error = respuesta, error
        self.pedidos = 0
        self.audios = 0

    def completar_json(self, sistema, mensaje):
        self.pedidos += 1
        if self.error:
            raise self.error
        return self.respuesta

    def transcribir(self, audio, nombre_archivo, glosario):
        self.audios += 1
        return "vacuné 20 vacas"


def test_si_el_principal_responde_no_se_usa_el_respaldo():
    principal, respaldo = Falso({"de": "principal"}), Falso({"de": "respaldo"})
    assert ConRespaldo(principal, respaldo).completar_json("s", "m") == {"de": "principal"}
    assert respaldo.pedidos == 0


@pytest.mark.parametrize("error", [IASaturada("OpenRouter 429"), ErrorIA("OpenRouter devolvió un JSON inválido")])
def test_si_el_principal_falla_responde_el_respaldo(error, caplog):
    principal, respaldo = Falso(error=error), Falso({"de": "respaldo"})
    assert ConRespaldo(principal, respaldo).completar_json("s", "m") == {"de": "respaldo"}
    assert "pruebo con el respaldo" in caplog.text


def test_los_audios_los_transcribe_el_respaldo():
    principal, respaldo = Falso(), Falso()
    assert ConRespaldo(principal, respaldo).transcribir(b"ogg", "a.ogg", "") == "vacuné 20 vacas"
    assert (principal.audios, respaldo.audios) == (0, 1)


def test_sin_clave_de_openrouter_todo_va_por_groq(monkeypatch):
    monkeypatch.setattr(config, "openrouter_api_key", "")
    assert isinstance(proveedor.armar(), ProveedorGroq)
    assert "Groq" in proveedor.describir() and "sin OPENROUTER_API_KEY" in proveedor.describir()


def test_con_clave_openrouter_es_el_principal_y_groq_el_respaldo(monkeypatch):
    monkeypatch.setattr(config, "openrouter_api_key", "clave-or")
    monkeypatch.setattr(config, "openrouter_esfuerzo", "high")
    armado = proveedor.armar()
    assert isinstance(armado, ConRespaldo)
    assert isinstance(armado.principal, ProveedorOpenRouter) and isinstance(armado.respaldo, ProveedorGroq)
    assert armado.principal.pedido("s", "m")["reasoning"] == {"effort": "high"}
    assert "OpenRouter" in proveedor.describir() and "Groq de respaldo" in proveedor.describir()


def test_openrouter_no_es_obligatoria_para_arrancar_en_produccion(monkeypatch):
    for variable in ("OPENROUTER_API_KEY", "OPENROUTER_MODELO", "OPENROUTER_ESFUERZO"):
        monkeypatch.delenv(variable, raising=False)
    c = Configuracion(
        _env_file=None,
        entorno="produccion",
        meta_app_secret="s",
        wa_verify_token="v",
        wa_token="t",
        wa_phone_number_id="1",
        groq_api_key="g",
        clave_hash="h",
    )
    assert c.faltantes_para_produccion() == []
    assert (c.openrouter_api_key, c.openrouter_modelo, c.openrouter_esfuerzo) == ("", "openai/gpt-oss-120b", "low")


def test_esfuerzo_invalido_no_arranca(monkeypatch):
    monkeypatch.setenv("OPENROUTER_ESFUERZO", "altísimo")
    with pytest.raises(ValueError, match="openrouter_esfuerzo"):
        Configuracion(_env_file=None)


# --- La IA saturada: mensaje claro --------------------------------------------------------


def test_con_la_ia_saturada_el_bot_avisa_que_pruebe_en_un_minuto(db, caplog):
    con_perfil(db, TELEFONO)
    proveedor.usar(
        ConRespaldo(Falso(error=IASaturada("OpenRouter 402")), Falso(error=IASaturada("RateLimitError 429")))
    )
    try:
        respuesta = pipeline.manejar_mensaje(db, TELEFONO, TEXTO, hoy=HOY)
    finally:
        proveedor.usar(None)
    assert respuesta == pipeline.DEMANDA == "⏳ Estoy con mucha demanda, probá de nuevo en un minuto."
    assert "IA con mucha demanda: RateLimitError 429" in caplog.text


class Saturada:
    """Groq con el límite de pedidos agotado, para el texto y para los audios."""

    def completar_json(self, sistema, mensaje):
        raise IASaturada("RateLimitError 429")

    def transcribir(self, audio, nombre_archivo, glosario):
        raise IASaturada("RateLimitError 429")


def test_la_ia_saturada_queda_en_el_log_sin_datos_personales(servidor, motor, monkeypatch, capsys):
    configurar_logs()
    con_perfil_en(motor, TELEFONO)
    monkeypatch.setattr(whatsapp, "descargar_media", lambda _id: b"ogg")
    proveedor.usar(Saturada())
    texto = {"from": TELEFONO, "id": "wamid.t", "timestamp": "1760000000", "type": "text", "text": {"body": TEXTO}}
    audio = {"from": TELEFONO, "id": "wamid.a", "timestamp": "1760000001", "type": "audio", "audio": {"id": "m1"}}
    try:
        with TestClient(main.app) as c:
            c.post("/webhook", json={"entry": [{"changes": [{"value": {"messages": [texto, audio]}}]}]})
            assert webhook.fila.esperar(5)
    finally:
        proveedor.usar(None)
    assert servidor == [(TELEFONO, pipeline.DEMANDA), (TELEFONO, pipeline.DEMANDA)]  # el texto y el audio
    salida = capsys.readouterr().out
    assert salida.count("IA con mucha demanda: RateLimitError 429") == 2
    assert TELEFONO not in salida and TEXTO not in salida and "Traceback" not in salida
