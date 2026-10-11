"""El bot solo registra, consulta datos propios y muestra precios oficiales."""

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import bot, config, llm, precios, senasa
from app.db import Base
from app.models import Cotizacion, Usuario

HOY = date(2026, 10, 9)
URL_PIZARRA = "https://www.cac.bcr.com.ar/es/precios-de-pizarra"
FUENTE = "Cámara Arbitral de Cereales - Bolsa de Comercio de Rosario"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as sesion:
        yield sesion


@pytest.fixture
def respuestas(monkeypatch):
    datos: dict[str, object] = {}
    monkeypatch.setattr(llm, "interpretar", lambda texto, hoy: datos[texto])
    return datos


def _usuario(db, telefono="5491100000001"):
    bot.manejar_mensaje(db, telefono, "crear campo La Prueba", hoy=HOY)
    return db.scalar(select(Usuario).where(Usuario.telefono == telefono))


@pytest.mark.parametrize("salida", [
    {"intencion": "fuera_de_alcance"},
    # Aunque el modelo devuelva texto propio, nunca se muestra.
    {"intencion": "charla", "respuesta": "Te recomiendo vender ya"},
    {"intencion": "registrar", "eventos": "no es una lista"},
    {"intencion": "consultar"},
    {"intencion": "precio", "precio": {}},
    ["no", "es", "un", "objeto"],
])
def test_todo_lo_que_no_es_valido_es_fuera_de_alcance(db, respuestas, salida):
    u = _usuario(db)
    respuestas["x"] = salida
    r = bot.manejar_mensaje(db, u.telefono, "x", hoy=HOY)
    assert r == bot.FUERA_DE_ALCANCE
    assert "recomiendo" not in r


def test_mensaje_largo_no_llega_a_la_ia(db, respuestas):
    u = _usuario(db)
    r = bot.manejar_mensaje(db, u.telefono, "a" * (config.MAX_LARGO_MENSAJE + 1), hoy=HOY)
    assert "muy largo" in r  # si hubiera llamado a la IA, respuestas[...] tiraría KeyError


def test_limite_diario(db, respuestas, monkeypatch):
    monkeypatch.setattr(config, "LIMITE_DIARIO_IA", 2)
    u = _usuario(db)
    respuestas["x"] = {"intencion": "fuera_de_alcance"}
    assert bot.manejar_mensaje(db, u.telefono, "x", hoy=HOY) == bot.FUERA_DE_ALCANCE
    assert bot.manejar_mensaje(db, u.telefono, "x", hoy=HOY) == bot.FUERA_DE_ALCANCE
    assert "límite" in bot.manejar_mensaje(db, u.telefono, "x", hoy=HOY)
    # al otro día se renueva
    assert bot.manejar_mensaje(db, u.telefono, "x", hoy=date(2026, 10, 10)) == bot.FUERA_DE_ALCANCE
    # los comandos no gastan cupo
    assert "Asistente de campo" in bot.manejar_mensaje(db, u.telefono, "ayuda", hoy=HOY)


def test_usuario_sin_campo_no_usa_la_ia(db, respuestas):
    r = bot.manejar_mensaje(db, "5491100000009", "¿a cuánto está la soja?", hoy=HOY)
    assert r == bot.BIENVENIDA
    assert not bot.puede_usar_ia(db, "5491100000009")


def _cargar_soja(db, fecha=date(2026, 10, 8), valor=310000, **extra):
    precios.guardar(db, FUENTE, URL_PIZARRA, "granos", [
        {"producto": "Soja", "plaza": "Rosario", "valor": valor, "unidad": "t", "fecha": fecha, **extra},
    ])


def test_precio_con_fuente_y_fecha(db, respuestas):
    u = _usuario(db)
    _cargar_soja(db, date(2026, 10, 7), 300000)
    _cargar_soja(db, date(2026, 10, 8), 310000)
    respuestas["¿a cuánto está la soja?"] = {"intencion": "precio", "precio": {"rubro": "granos", "producto": "soja"}}

    r = bot.manejar_mensaje(db, u.telefono, "¿a cuánto está la soja?", hoy=HOY)
    assert "Soja (Rosario): *$ 310.000 por t* (ARS)" in r
    assert "Publicado el 08/10/2026" in r
    assert "La fuente no informa si incluye impuestos u otros costos." in r
    assert "300.000" not in r  # solo el último
    assert f"Fuente: {FUENTE}" in r and URL_PIZARRA in r
    assert "No son una recomendación" in r
    assert "puede no estar actualizado" not in r


def test_precio_viejo_avisa(db):
    _cargar_soja(db, date(2026, 9, 1))
    assert "dato de hace 38 días, puede no estar actualizado" in precios.responder(db, "soja", None, HOY)


def test_precio_aclara_costos_adicionales(db):
    _cargar_soja(db, incluye_impuestos="no", costos_adicionales="Precio orientativo, sin gastos comerciales")
    r = precios.responder(db, "soja", None, HOY)
    assert "No incluye impuestos (IVA). Precio orientativo, sin gastos comerciales." in r


def test_moneda_desconocida_se_rechaza(db):
    with pytest.raises(ValueError):
        _cargar_soja(db, moneda="EUR")


def test_sin_precio_no_inventa(db, respuestas):
    u = _usuario(db)
    respuestas["precio del novillo"] = {"intencion": "precio", "precio": {"rubro": "hacienda", "producto": "novillos"}}
    r = bot.manejar_mensaje(db, u.telefono, "precio del novillo", hoy=HOY)
    assert "No tengo precios cargados de ese producto" in r


def test_solo_acepta_fuentes_oficiales(db):
    for url in ("https://www.preciosdelcampo.com/soja", "http://www.bcr.com.ar/x", "https://bcr.com.ar.trucho.com/x"):
        with pytest.raises(ValueError):
            precios.guardar(db, "Otra", url, "granos", [{"producto": "soja", "valor": 1, "unidad": "t", "fecha": HOY}])
    assert precios.es_oficial("https://www.magyp.gob.ar/precios")
    assert precios.es_oficial(URL_PIZARRA)
    assert db.scalar(select(Cotizacion)) is None


def test_guardar_precio_dos_veces_no_duplica(db):
    _cargar_soja(db, valor=300000)
    _cargar_soja(db, valor=310000)
    filas = db.scalars(select(Cotizacion)).all()
    assert len(filas) == 1 and filas[0].valor == 310000 and filas[0].producto == "soja"


URL_SENASA = "https://www.argentina.gob.ar/senasa/registro-productos-veterinarios"


def _cargar_senasa(db):
    senasa.reemplazar_registro(db, [
        {"nombre": "Ivomec 1%", "registro": "12.345", "titular": "Lab Uno SA",
         "principio_activo": "Ivermectina", "estado": "Vigente"},
        {"nombre": "Bioaftógen", "registro": "98.765", "titular": "Lab Dos SA",
         "principio_activo": "Virus aftosa inactivado", "estado": "Vigente"},
    ], date(2026, 10, 1), URL_SENASA)


def test_senasa_por_principio_activo(db, respuestas):
    u = _usuario(db)
    _cargar_senasa(db)
    respuestas["¿la ivermectina está aprobada?"] = {
        "intencion": "producto_veterinario", "producto_veterinario": {"nombre": "IVERMECTINA"}}
    r = bot.manejar_mensaje(db, u.telefono, "¿la ivermectina está aprobada?", hoy=HOY)
    assert "*Ivomec 1%*" in r and "Registro SENASA N° 12.345" in r and "Titular: Lab Uno SA" in r
    assert "Estado: vigente" in r
    assert "datos al 01/10/2026" in r and URL_SENASA in r
    assert "$" not in r  # nunca precios


def test_senasa_sin_tildes_y_sin_resultados(db):
    _cargar_senasa(db)
    assert "Bioaftógen" in senasa.responder(db, "bioaftogen")
    r = senasa.responder(db, "productoinexistente")
    assert "No encontré ese producto" in r and "no confirma que no esté registrado" in r


def test_senasa_solo_acepta_gob_ar(db):
    with pytest.raises(ValueError):
        senasa.reemplazar_registro(db, [{"nombre": "x", "registro": "1"}], HOY, URL_PIZARRA)
    with pytest.raises(ValueError):  # un archivo vacío no borra el registro
        senasa.reemplazar_registro(db, [], HOY, URL_SENASA)
