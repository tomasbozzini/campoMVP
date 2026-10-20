"""Un campo nuevo con un nombre muy parecido a uno que ya existe ("Omu" y "El Ombú"): antes de
crearlo se pregunta si es el mismo (paso 8.5 del plan). Lo del mensaje se hace después de la
respuesta."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.ia import interprete
from app.infra.modelos import Establecimiento, Evento, Pendiente
from app.nucleo import pipeline
from app.nucleo.normalizar import PARECIDO_MINIMO, clave_establecimiento, parecido
from tests.ayudas import con_perfil

HOY = date(2026, 10, 15)
TEL = "5491100000001"
AHORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
LLUVIA = {"categoria": "campo", "tipo": "lluvia", "valor": 20, "unidad": "mm"}


@pytest.fixture
def ia(monkeypatch):
    respuestas: dict[str, object] = {
        "estoy en el ombú": {"intencion": "establecimiento", "establecimiento": "El Ombú"},
        "llovió 20 mm en omu": {"intencion": "registrar", "establecimiento": "Omu", "eventos": [LLUVIA]},
        "mostrame mis campos": {"intencion": "mis_campos"},
    }
    reloj = {"ahora": AHORA}
    monkeypatch.setattr(pipeline, "_ahora", lambda: reloj["ahora"])
    monkeypatch.setattr(interprete, "interpretar", lambda texto, *_a, **_k: respuestas[texto])
    return respuestas, reloj


def _mandar(db, texto):
    return pipeline.manejar_mensaje(db, TEL, texto, hoy=HOY)


def _campos(db) -> list[str]:
    return list(db.scalars(select(Establecimiento.nombre).order_by(Establecimiento.id)))


def _lluvias(db) -> list[str | None]:
    return [e.nombre_establecimiento for e in db.scalars(select(Evento))]


@pytest.mark.parametrize(
    ("nombre", "otro", "es_parecido"),
    [
        ("Omu", "El Ombú", True),
        ("Ombú", "El Ombú", True),  # sin el artículo son iguales
        ("La Esperanza", "Esperanza", True),
        ("Don Carlos", "Don Carlo", True),
        ("Santa Rosa", "Santa Rita", False),
        ("La Pastora", "La Paloma", False),
        ("El Retiro", "El Refugio", False),
    ],
)
def test_que_nombres_se_parecen(nombre, otro, es_parecido):
    clave, otra = clave_establecimiento(nombre) or "", clave_establecimiento(otro) or ""
    assert (parecido(clave, otra) >= PARECIDO_MINIMO) is es_parecido


def test_pregunta_antes_de_crear_un_campo_parecido_y_no_anota_nada(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en el ombú")
    r = _mandar(db, "llovió 20 mm en omu")
    assert r.startswith("🤔 *¿Omu es El Ombú?*\n\nYa tenés cargado el campo *El Ombú*.")
    assert "Respondé *sí* para anotarlo en El Ombú, *no* para crear el campo *Omu*, *cambiale el nombre*" in r
    assert _campos(db) == ["El Ombú"] and _lluvias(db) == []


def test_si_es_el_mismo_lo_anota_ahi(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en el ombú")
    _mandar(db, "llovió 20 mm en omu")
    r = _mandar(db, "sí, es ese")
    assert r.startswith("✅") and "El Ombú" in r
    assert _campos(db) == ["El Ombú"] and _lluvias(db) == ["El Ombú"]


def test_si_es_otro_crea_el_campo_nuevo(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en el ombú")
    _mandar(db, "llovió 20 mm en omu")
    _mandar(db, "no")
    assert _campos(db) == ["El Ombú", "Omu"] and _lluvias(db) == ["Omu"]
    # La próxima vez Omu ya existe: no pregunta más.
    assert _mandar(db, "llovió 20 mm en omu").startswith("✅")
    assert _lluvias(db) == ["Omu", "Omu"]


@pytest.mark.parametrize("texto", ["cancelá", "no, dejá", "olvidate"])
def test_cancelar_no_anota_nada(db, ia, texto):
    con_perfil(db, TEL)
    _mandar(db, "estoy en el ombú")
    _mandar(db, "llovió 20 mm en omu")
    assert _mandar(db, texto) == "👌 Listo, no anoté nada."
    assert _campos(db) == ["El Ombú"] and _lluvias(db) == []


def test_otro_mensaje_descarta_la_pregunta(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en el ombú")
    _mandar(db, "llovió 20 mm en omu")
    assert "El Ombú" in _mandar(db, "mostrame mis campos")
    assert _mandar(db, "sí") != "👌 Listo, no anoté nada."  # la pregunta ya no está
    assert _campos(db) == ["El Ombú"] and _lluvias(db) == []


def test_si_pasa_mucho_tiempo_no_anota_nada(db, ia):
    _, reloj = ia
    con_perfil(db, TEL)
    _mandar(db, "estoy en el ombú")
    _mandar(db, "llovió 20 mm en omu")
    reloj["ahora"] = AHORA + timedelta(minutes=11)
    assert _mandar(db, "sí").startswith("⏱️ Pasó mucho tiempo")
    assert _lluvias(db) == []


def test_lo_que_ya_se_habia_hecho_del_mensaje_se_deshace_hasta_la_respuesta(db, ia):
    """Un mensaje con un pendiente y una lluvia en "Omu": no queda nada hasta que responde."""
    respuestas, _ = ia
    con_perfil(db, TEL)
    _mandar(db, "estoy en el ombú")
    respuestas["anotame que tengo que llamar a juan y llovió 20 en omu"] = {
        "acciones": [
            {"intencion": "anotar_pendiente", "pendiente": {"texto": "llamar a Juan"}},
            {"intencion": "registrar", "establecimiento": "Omu", "eventos": [LLUVIA]},
        ]
    }
    assert _mandar(db, "anotame que tengo que llamar a juan y llovió 20 en omu").startswith("🤔 *¿Omu es El Ombú?*")
    assert db.scalars(select(Pendiente)).all() == [] and _lluvias(db) == []
    r = _mandar(db, "dale")
    assert "PENDIENTE ANOTADO" in r and _lluvias(db) == ["El Ombú"]
    assert [p.texto for p in db.scalars(select(Pendiente))] == ["llamar a Juan"]


def test_dos_campos_parecidos_en_el_mismo_mensaje_pregunta_de_a_uno(db, ia):
    respuestas, _ = ia
    con_perfil(db, TEL)
    _mandar(db, "estoy en el ombú")
    respuestas["estoy en la pastora"] = {"intencion": "establecimiento", "establecimiento": "La Pastora"}
    _mandar(db, "estoy en la pastora")
    respuestas["llovió en omu y en pastora"] = {
        "acciones": [
            {"intencion": "registrar", "establecimiento": "Omu", "eventos": [LLUVIA]},
            {"intencion": "registrar", "establecimiento": "Pastora", "eventos": [LLUVIA]},
        ]
    }
    assert _mandar(db, "llovió en omu y en pastora").startswith("🤔 *¿Omu es El Ombú?*")
    assert _mandar(db, "sí").startswith("🤔 *¿Pastora es La Pastora?*")
    _mandar(db, "sí")
    assert sorted(_lluvias(db)) == ["El Ombú", "La Pastora"]  # type: ignore[type-var]
    assert _campos(db) == ["El Ombú", "La Pastora"]
