"""Perfil: las preguntas fijas del alta (sin IA), "mis datos", "cambiar rubro" y "cambiar matrícula"."""

from datetime import date

import pytest
from sqlalchemy import select

from app.ia import interprete
from app.infra.config import config
from app.infra.modelos import MensajeChat, Usuario
from app.nucleo import perfil, pipeline, usuarios
from tests.ayudas import con_perfil

HOY = date(2026, 10, 15)
TEL = "5491100000001"


@pytest.fixture
def ia(monkeypatch):
    """La IA falsa: anota qué textos le llegaron y responde un saludo."""
    llamadas: list[str] = []

    def interpretar(texto, hoy, historial=None, partes=()):
        llamadas.append(texto)
        return {"intencion": "saludo"}

    monkeypatch.setattr(interprete, "interpretar", interpretar)
    return llamadas


def _mandar(db, texto, telefono=TEL):
    return pipeline.manejar_mensaje(db, telefono, texto, hoy=HOY)


def test_un_usuario_existente_responde_las_preguntas_y_despues_sigue(db, ia):
    usuarios.autorizar(db, TEL)  # como quedan los usuarios de antes del perfil

    r = _mandar(db, "vacuné 20 vacas")
    assert "Soy CampoBot" in r and "3 datos tuyos" in r and perfil.PREGUNTAS["nombre"] in r
    assert ia == []  # el mensaje no llega a la IA ni se anota

    assert perfil.PREGUNTAS["rubro"] in _mandar(db, "me llamo juana GÓMEZ")
    assert perfil.PREGUNTAS["localidad"] in _mandar(db, "1")
    r = _mandar(db, "  tres   ARROYOS ")
    assert "¡Listo, Juana!" in r and "mandámelo de nuevo" in r

    u = db.scalar(select(Usuario).where(Usuario.telefono == TEL))
    assert (u.nombre_completo, u.rubro, u.localidad, u.pregunta) == ("Juana Gómez", "veterinario", "Tres Arroyos", None)
    assert ia == []
    assert db.scalar(select(MensajeChat)) is None  # nada del alta va a la charla que ve la IA

    _mandar(db, "vacuné 20 vacas")
    assert ia == ["vacuné 20 vacas"]


def test_una_respuesta_que_no_sirve_repite_la_pregunta(db, ia):
    usuarios.autorizar(db, TEL)
    _mandar(db, "hola")
    r = _mandar(db, "Juana")  # falta el apellido
    assert perfil.NO_ENTENDI["nombre"] in r and perfil.PREGUNTAS["nombre"] in r
    _mandar(db, "Juana Gómez")
    r = _mandar(db, "veterinaria y productora")  # dos rubros: no adivina
    assert perfil.NO_ENTENDI["rubro"] in r and perfil.PREGUNTAS["rubro"] in r
    assert perfil.PREGUNTAS["localidad"] in _mandar(db, "Productora")
    assert ia == []


def test_si_falta_un_solo_dato_pregunta_solo_ese(db, ia):
    u = con_perfil(db, TEL)
    u.rubro = None
    r = _mandar(db, "hola")
    assert "un dato tuyo" in r and perfil.PREGUNTAS["rubro"] in r
    assert "Listo" in _mandar(db, "agrónomo")
    assert u.rubro == "agronomo" and u.localidad == "Tandil"


def test_a_quien_tenia_rubro_otro_se_le_vuelve_a_preguntar(db, ia):
    """La opción "Otro" se sacó: la próxima vez que escribe, elige uno de los tres."""
    u = con_perfil(db, TEL, rubro="otro")
    r = _mandar(db, "vacuné 20 vacas")
    assert perfil.RUBRO_DE_NUEVO in r and perfil.PREGUNTAS["rubro"] in r
    assert "Otro" not in r and "*4*" not in r
    assert ia == []  # el mensaje no llega a la IA ni se anota

    r = _mandar(db, "4")
    assert perfil.NO_ENTENDI["rubro"] in r and "del 1 al 3" in r
    assert u.rubro == "otro"
    r = _mandar(db, "3")
    assert "¡Listo, Juana!" in r and "mandámelo de nuevo" in r
    assert (u.rubro, u.nombre_completo, u.localidad, u.pregunta) == ("productor", "Juana Gómez", "Tandil", None)

    _mandar(db, "vacuné 20 vacas")
    assert ia == ["vacuné 20 vacas"]


def test_el_rubro_se_elige_entre_tres_opciones(db, ia):
    con_perfil(db, TEL)
    r = _mandar(db, "cambiar rubro")
    assert "*1* Veterinario" in r and "*3* Productor" in r and "Otro" not in r
    _mandar(db, "4")  # no es una opción: el cambio se descarta y sigue el camino normal
    assert db.scalar(select(Usuario).where(Usuario.telefono == TEL)).rubro == "productor"


def test_ayuda_y_privacidad_se_responden_durante_el_alta(db, ia):
    usuarios.autorizar(db, TEL)
    r = _mandar(db, "ayuda")
    assert "CAMPOBOT" in r and perfil.PREGUNTAS["nombre"] in r
    r = _mandar(db, "privacidad")
    assert "TUS DATOS" in r and perfil.PREGUNTAS["nombre"] in r
    assert "Soy CampoBot" not in r  # la presentación va una sola vez
    assert perfil.PREGUNTAS["rubro"] in _mandar(db, "Juana Gómez")


def test_borrar_mis_datos_funciona_durante_el_alta(db, ia):
    usuarios.autorizar(db, TEL)
    _mandar(db, "hola")
    assert "BORRAR TODOS TUS DATOS" in _mandar(db, "borrar mis datos")
    assert "DATOS BORRADOS" in _mandar(db, "confirmo borrar mis datos")
    assert db.scalar(select(Usuario)) is None


def test_los_administradores_tambien_responden_las_preguntas(db, ia, monkeypatch):
    monkeypatch.setattr(config, "admin_telefonos", {TEL})
    assert perfil.PREGUNTAS["nombre"] in _mandar(db, "autorizar 5491100000002")
    assert db.scalar(select(Usuario).where(Usuario.telefono == "5491100000002")) is None


def test_mis_datos_muestra_el_perfil_y_no_va_a_la_charla(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, "Mis datos")
    for dato in ("MIS DATOS", "Juana Gómez", "Veterinario", "Tandil", "sin cargar", "cambiar rubro"):
        assert dato in r
    assert db.scalar(select(MensajeChat)) is None
    assert ia == []


def test_cambiar_rubro(db, ia):
    u = con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, "cambiar rubro")
    assert "Veterinario" in r and perfil.PREGUNTAS["rubro"] in r
    assert "Agrónomo o asesor" in _mandar(db, "2")
    assert u.rubro == "agronomo" and u.pregunta is None

    _mandar(db, "cambiar rubro")
    assert _mandar(db, "cancelar") == perfil.SIN_CAMBIOS
    assert u.rubro == "agronomo"
    assert ia == []


def test_cambiar_rubro_y_mandar_otra_cosa_descarta_el_cambio(db, ia):
    u = con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, "cambiar rubro")
    _mandar(db, "vacuné 20 vacas")
    assert ia == ["vacuné 20 vacas"]  # siguió el camino normal
    assert u.rubro == "veterinario" and u.pregunta is None


def test_cambiar_matricula(db, ia):
    u = con_perfil(db, TEL)
    assert perfil.PREGUNTA_MATRICULA in _mandar(db, "cambiar matrícula")
    assert "MP 1234" in _mandar(db, "MP  1234")
    assert u.matricula == "MP 1234"
    assert "MP 1234" in _mandar(db, "mis datos")

    _mandar(db, "cambiar matricula")
    assert "borré" in _mandar(db, "ninguna")
    assert u.matricula is None

    _mandar(db, "cambiar matricula")
    _mandar(db, "llovieron 20 mm")  # no es una matrícula: sigue el camino normal
    assert u.matricula is None and ia == ["llovieron 20 mm"]


@pytest.mark.parametrize(
    ("texto", "rubro"),
    [
        ("1", "veterinario"),
        ("2.", "agronomo"),
        ("opción 3", "productor"),
        ("4", None),  # era "Otro", que ya no está
        ("Soy veterinaria", "veterinario"),
        ("Ingeniero agrónomo", "agronomo"),
        ("asesor", "agronomo"),
        ("productor", "productor"),
        ("otro", None),
        ("otra cosa", None),
        ("5", None),
        ("veterinario y productor", None),
        ("no sé", None),
    ],
)
def test_leer_rubro(texto, rubro):
    assert perfil.leer_rubro(texto) == rubro


@pytest.mark.parametrize(
    ("texto", "nombre"),
    [
        ("juan perez", "Juan Perez"),
        ("me llamo MARÍA DE LOS ÁNGELES gómez", "María de los Ángeles Gómez"),
        ("Soy Ana O'Brien.", "Ana O'Brien"),
        ("Juan", None),
        ("autorizar 5491100000002", None),
        ("", None),
    ],
)
def test_leer_nombre(texto, nombre):
    assert perfil.leer_nombre(texto) == nombre


@pytest.mark.parametrize(
    ("texto", "localidad"),
    [
        ("  tres   ARROYOS ", "Tres Arroyos"),
        ("25 de mayo", "25 de Mayo"),
        ("soy de tandil", "Tandil"),
        ("villa gesell.", "Villa Gesell"),
        ("123", None),
        ("", None),
    ],
)
def test_leer_localidad(texto, localidad):
    assert perfil.leer_localidad(texto) == localidad


@pytest.mark.parametrize(
    ("texto", "matricula"),
    [
        ("MP  1234", "MP 1234"),
        ("M.P. 1234", "M.P. 1234"),
        ("CMVPBA 5678", "CMVPBA 5678"),
        ("Mat. Prov. 1234/5", "Mat. Prov. 1234/5"),
        ("12345", "12345"),
        ("llovieron 20 mm", None),
        ("vacuné 20 vacas", None),
        ("MP", None),
    ],
)
def test_leer_matricula(texto, matricula):
    assert perfil.leer_matricula(texto) == matricula
