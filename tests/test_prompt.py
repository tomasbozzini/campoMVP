"""El prompt y el glosario de los audios se arman con los módulos del rubro de cada persona."""

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import main, modulos
from app.api import webhook
from app.canales import whatsapp
from app.ia import prompt, proveedor
from app.ia.esquemas import EsquemaAccion
from app.ia.prompt import Parte
from app.infra.modelos import Evento
from app.nucleo import acciones, pipeline
from app.nucleo.acciones import Accion
from app.nucleo.cuaderno import Cuaderno
from app.nucleo.perfil import RUBROS
from tests.ayudas import con_perfil, con_perfil_en

HOY = date(2026, 10, 13)
TACTO_ANOTADO = "🐄 Tacto anotado"
PARTE_TACTO = Parte(
    intenciones=("tacto",),
    campos='  "tacto": TACTO | null          // solo si intencion = "tacto"',
    descripciones='- "tacto": informa el resultado de un tacto.',
    pedidos='Cada rodeo es una acción "tacto" aparte.',
    formatos='TACTO:\n{\n  "prenadas": int | null\n}',
    reglas="- Los porcentajes de preñez no se calculan: se informa lo que dicta.",
)


GLOSARIO_GANADERO = ("raspaje", "tricomoniasis", "vaquillonas")


@pytest.fixture
def ganaderia(monkeypatch):
    """Un módulo ganadero de mentira, que tienen los veterinarios y los productores."""
    monkeypatch.setattr(acciones, "_registro", dict(acciones._registro))
    monkeypatch.setattr(modulos, "_partes", dict(modulos._partes))
    monkeypatch.setattr(modulos, "_glosarios", dict(modulos._glosarios))
    monkeypatch.setattr(modulos, "MODULOS", [*modulos.MODULOS, "ganaderia"])
    accion = Accion("tacto", EsquemaAccion, lambda _ctx, _datos: TACTO_ANOTADO)
    modulos.registrar("ganaderia", [accion], PARTE_TACTO, GLOSARIO_GANADERO)


class ProveedorFalso:
    def __init__(self, respuesta: object) -> None:
        self.respuesta = respuesta
        self.sistemas: list[str] = []
        self.glosarios: list[str] = []

    def completar_json(self, sistema: str, mensaje: str) -> object:
        self.sistemas.append(sistema)
        return self.respuesta

    def transcribir(self, audio: bytes, nombre_archivo: str, glosario: str) -> str:
        self.glosarios.append(glosario)
        return "tacto 30 vacas"


@pytest.fixture
def ia():
    falso = ProveedorFalso({"acciones": [{"intencion": "tacto"}]})
    proveedor.usar(falso)
    yield falso
    proveedor.usar(None)


@pytest.mark.parametrize("rubro", [*RUBROS, None, "otro"])
def test_hoy_todos_los_rubros_usan_solo_el_modulo_comun(rubro):
    """Ganadería y agricultura todavía no existen: nadie las tiene en el prompt."""
    assert modulos.del_rubro(rubro) == ["comun"]


def test_cada_rubro_suma_los_modulos_que_le_tocan(monkeypatch):
    monkeypatch.setattr(modulos, "MODULOS", ["comun", "ganaderia", "agricultura"])
    assert modulos.del_rubro("veterinario") == ["comun", "ganaderia"]
    assert modulos.del_rubro("agronomo") == ["comun", "agricultura"]
    assert modulos.del_rubro("productor") == ["comun", "ganaderia", "agricultura"]


def test_cada_modulo_suma_su_parte_en_su_lugar(ganaderia):
    sistema = prompt.sistema(modulos.partes(["comun", "ganaderia"]))

    def antes(*textos: str) -> bool:
        posiciones = [sistema.index(t) for t in textos]
        return posiciones == sorted(posiciones)

    assert '"producto_veterinario" | "tacto" | "fuera_de_alcance",' in sistema
    assert antes('"producto_veterinario": {', '"tacto": TACTO | null', "}\n\nQué es cada intención")
    assert antes('- "saludo":', '- "tacto":', '- "fuera_de_alcance":')
    assert antes('acción "registrar" con varios eventos.', "Cada rodeo", "Devolvé ÚNICAMENTE")
    assert antes("PRECIO:", "TACTO:", "Reglas:")
    assert antes('"La Esperanza" en "establecimiento".', "- Los porcentajes", "- Si una parte del mensaje")


def test_sin_el_modulo_su_parte_no_esta_en_el_prompt(ganaderia):
    sistema = prompt.sistema(modulos.partes(["comun"]))
    for texto in ('"tacto"', "TACTO", "Cada rodeo", "porcentajes de preñez"):
        assert texto not in sistema, texto


def test_cada_persona_recibe_el_prompt_de_su_rubro(db, ganaderia, ia):
    veterinaria = con_perfil(db, "5491100000001", rubro="veterinario")
    agronoma = con_perfil(db, "5491100000002", rubro="agronomo")
    pipeline.manejar_mensaje(db, veterinaria.telefono, "tacto 30 vacas", hoy=HOY)
    pipeline.manejar_mensaje(db, agronoma.telefono, "tacto 30 vacas", hoy=HOY)
    assert ia.sistemas == [
        prompt.sistema(modulos.partes(["comun", "ganaderia"])),
        prompt.sistema(modulos.partes(["comun"])),
    ]


def test_una_accion_de_un_modulo_que_no_tiene_no_se_ejecuta(db, ganaderia, ia):
    """Aunque la IA la devuelva: el código decide qué puede hacer cada persona."""
    veterinaria = con_perfil(db, "5491100000001", rubro="veterinario")
    agronoma = con_perfil(db, "5491100000002", rubro="agronomo")
    assert pipeline.manejar_mensaje(db, veterinaria.telefono, "tacto 30 vacas", hoy=HOY) == TACTO_ANOTADO
    assert pipeline.manejar_mensaje(db, agronoma.telefono, "tacto 30 vacas", hoy=HOY) == pipeline.FUERA_DE_ALCANCE


def test_el_prompt_de_un_modulo_ofrece_justo_sus_acciones(monkeypatch):
    monkeypatch.setattr(acciones, "_registro", dict(acciones._registro))
    monkeypatch.setattr(modulos, "_partes", dict(modulos._partes))
    accion = Accion("tacto", EsquemaAccion, lambda _ctx, _datos: TACTO_ANOTADO)
    with pytest.raises(ValueError, match="ganaderia"):
        modulos.registrar("ganaderia", [accion], Parte(intenciones=("tacto", "raspaje"), campos="", descripciones=""))
    with pytest.raises(ValueError, match="ganaderia"):
        modulos.registrar("ganaderia", [accion], Parte(intenciones=(), campos="", descripciones=""))
    assert acciones.buscar("tacto") is None and "ganaderia" not in modulos._partes


# --- Glosario para Whisper ------------------------------------------------------------


def test_el_glosario_del_modulo_comun():
    glosario = modulos.glosario(["comun"])
    assert glosario.startswith("vaquillonas, novillos, terneros, ") and glosario.endswith(", cebada.")
    assert "ivermectina" in glosario and "SENASA" in glosario


def test_cada_modulo_suma_su_glosario_sin_repetir(ganaderia):
    comun = modulos.glosario(["comun"])
    con_ganaderia = modulos.glosario(["comun", "ganaderia"])
    assert con_ganaderia == comun.removesuffix(".") + ", raspaje, tricomoniasis."  # vaquillonas ya estaba
    assert "raspaje" not in comun


def test_sin_palabras_el_glosario_queda_vacio(ganaderia):
    modulos.registrar("vacio", [], Parte(intenciones=(), campos="", descripciones=""))
    assert modulos.glosario(["vacio"]) == ""


@pytest.mark.parametrize("rubro", list(RUBROS))
def test_el_glosario_de_cada_rubro_entra_en_whisper(rubro):
    """Whisper lee como mucho 224 tokens de glosario: con más, falla o lo corta."""
    assert len(modulos.glosario(modulos.del_rubro(rubro))) <= modulos.LARGO_MAXIMO_GLOSARIO


@pytest.mark.parametrize("rubro", list(RUBROS))
def test_el_prompt_de_cada_rubro_no_pasa_el_tope(rubro):
    """Cada carácter de más se paga y se espera en cada mensaje."""
    sistema = prompt.sistema(modulos.partes(modulos.del_rubro(rubro)))
    assert len(sistema) <= modulos.LARGO_MAXIMO_PROMPT


def test_cada_audio_se_transcribe_con_el_glosario_de_su_rubro(servidor, motor, ganaderia, ia, monkeypatch):
    con_perfil_en(motor, "5491100000001", rubro="veterinario")
    con_perfil_en(motor, "5491100000002", rubro="agronomo")
    monkeypatch.setattr(whatsapp, "descargar_media", lambda _id: b"ogg")

    def audio(telefono: str, wamid: str) -> dict:
        mensaje = {"from": telefono, "id": wamid, "type": "audio", "audio": {"id": "media1"}}
        return {"entry": [{"changes": [{"value": {"messages": [mensaje]}}]}]}

    with TestClient(main.app) as c:
        c.post("/webhook", json=audio("5491100000001", "wamid.v"))
        assert webhook.fila.esperar(5)
        c.post("/webhook", json=audio("5491100000002", "wamid.a"))
        assert webhook.fila.esperar(5)
    assert ia.glosarios == [modulos.glosario(["comun", "ganaderia"]), modulos.glosario(["comun"])]
    assert servidor[0] == ("5491100000001", f"🎤 _tacto 30 vacas_\n\n{TACTO_ANOTADO}")


def test_el_prompt_no_lleva_la_fecha_de_hoy():
    """La IA no calcula fechas (paso 8.5.1): devuelve lo que dijo la persona como FECHA y el
    código la calcula. El prompt es el mismo todos los días."""
    sistema = prompt.sistema(modulos.partes(["comun"]))
    assert '"fecha_evento": FECHA | null' in sistema and '"vence": FECHA | null' in sistema
    assert re.search(r"20\d\d-\d\d-\d\d", sistema) is None


def test_el_glosario_suma_los_nombres_propios_que_entran():
    base = modulos.glosario(["comun"])
    con_nombres = modulos.glosario(["comun"], ["El Ombú", "potrero grande", "El Ombú"])
    assert con_nombres == base.removesuffix(".") + ", El Ombú, potrero grande."
    muchos = [f"Estancia Número {i:03}" for i in range(40)]
    glosario = modulos.glosario(["comun"], muchos)
    assert len(glosario) <= modulos.LARGO_MAXIMO_GLOSARIO
    assert glosario.startswith(base.removesuffix(".")) and "Estancia Número 000" in glosario
    assert "Estancia Número 039" not in glosario  # los que no entran quedan afuera


def test_cada_audio_se_transcribe_con_los_campos_y_lotes_de_la_persona(servidor, motor, ia, monkeypatch):
    with sessionmaker(bind=motor)() as db:
        u = con_perfil(db, "5491100000001")
        cuaderno = Cuaderno(db, u)
        ombu, pastora = cuaderno.establecimiento("El Ombú"), cuaderno.establecimiento("La Pastora")
        cuaderno.lote("potrero grande", ombu)
        cuaderno.lote("3", ombu)  # los números no hacen falta
        cuaderno.agregar([Evento(establecimiento=pastora, categoria="campo", tipo="lluvia", fecha_evento=HOY)])
        db.commit()
    monkeypatch.setattr(whatsapp, "descargar_media", lambda _id: b"ogg")
    mensaje = {"from": "5491100000001", "id": "wamid.o", "type": "audio", "audio": {"id": "media1"}}
    with TestClient(main.app) as c:
        c.post("/webhook", json={"entry": [{"changes": [{"value": {"messages": [mensaje]}}]}]})
        assert webhook.fila.esperar(5)
    # Primero el campo con más registros.
    assert ia.glosarios == [modulos.glosario(["comun"], ["La Pastora", "El Ombú", "potrero grande"])]
