import hashlib
import hmac
import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import bot, config, llm, whatsapp
from app.db import Base
from app.models import Evento, Usuario

HOY = date(2026, 10, 9)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as sesion:
        yield sesion


@pytest.fixture
def fake_llm(monkeypatch):
    """Reemplaza al modelo: `respuestas` mapea texto -> JSON interpretado."""
    respuestas: dict[str, dict] = {}
    llamadas: list[str] = []

    def interpretar(texto, hoy):
        llamadas.append(texto)
        return respuestas[texto]

    monkeypatch.setattr(llm, "interpretar", interpretar)
    return respuestas, llamadas


def _con_campo(db, telefono="5492494000001", nombre="La Esperanza"):
    bot.manejar_mensaje(db, telefono, f"crear campo {nombre}", hoy=HOY)
    return db.scalar(select(Usuario).where(Usuario.telefono == telefono))


def test_usuario_nuevo_recibe_bienvenida(db):
    assert "crear campo" in bot.manejar_mensaje(db, "5491100000000", "hola", hoy=HOY)


def test_crear_campo_y_unirse(db):
    admin = _con_campo(db)
    assert admin.rol == "admin"
    codigo = admin.campo.codigo_invitacion

    r = bot.manejar_mensaje(db, "5491100000002", f"unirme {codigo.lower()}", hoy=HOY)
    assert "Te sumaste a *La Esperanza*" in r
    peon = db.scalar(select(Usuario).where(Usuario.telefono == "5491100000002"))
    assert peon.campo_id == admin.campo_id and peon.rol == "miembro"

    assert "No encontré" in bot.manejar_mensaje(db, "5491100000003", "unirme ZZZZZZ", hoy=HOY)


def test_registrar_vacunacion(db, fake_llm):
    respuestas, _ = fake_llm
    usuario = _con_campo(db)
    texto = "se vacunaron 20 vacas en el lote 3 contra aftosa"
    respuestas[texto] = {
        "intencion": "registrar",
        "eventos": [{
            "categoria": "sanidad", "tipo": "vacunacion", "producto": "aftosa",
            "cantidad_animales": 20, "categoria_animal": "Vacas", "lote": "Lote 3",
            "fecha_evento": "2026-10-09", "confianza": "alta",
        }],
    }
    r = bot.manejar_mensaje(db, usuario.telefono, texto, hoy=HOY)
    assert "Vacunación (aftosa) · 20 vacas · lote 3 · 09/10/2026" in r

    evento = db.scalar(select(Evento))
    assert evento.campo_id == usuario.campo_id
    assert evento.lote == "3"
    assert evento.mensaje_original == texto


def test_fecha_futura_o_invalida_usa_hoy(db, fake_llm):
    respuestas, _ = fake_llm
    usuario = _con_campo(db)
    respuestas["llovio"] = {
        "intencion": "registrar",
        "eventos": [
            {"categoria": "campo", "tipo": "lluvia", "valor": 30, "unidad": "mm", "fecha_evento": "2027-01-01"},
            {"categoria": "campo", "tipo": "lluvia", "valor": 5, "unidad": "mm", "fecha_evento": "ayer"},
            {"categoria": "inventada", "tipo": "x"},
        ],
    }
    bot.manejar_mensaje(db, usuario.telefono, "llovio", hoy=HOY)
    eventos = db.scalars(select(Evento)).all()
    assert len(eventos) == 2
    assert all(e.fecha_evento == HOY for e in eventos)


def test_borrar_deshace_el_ultimo_mensaje(db, fake_llm):
    respuestas, _ = fake_llm
    usuario = _con_campo(db)
    respuestas["a"] = {"intencion": "registrar", "eventos": [{"categoria": "campo", "tipo": "lluvia", "valor": 10, "unidad": "mm"}]}
    respuestas["b"] = {
        "intencion": "registrar",
        "eventos": [
            {"categoria": "movimiento", "tipo": "nacimiento", "cantidad_animales": 3, "categoria_animal": "terneros"},
            {"categoria": "movimiento", "tipo": "muerte", "cantidad_animales": 1, "categoria_animal": "terneros"},
        ],
    }
    bot.manejar_mensaje(db, usuario.telefono, "a", hoy=HOY)
    bot.manejar_mensaje(db, usuario.telefono, "b", hoy=HOY)

    r = bot.manejar_mensaje(db, usuario.telefono, "borrar", hoy=HOY)
    assert "Nacimiento" in r and "Muerte" in r
    restantes = db.scalars(select(Evento)).all()
    assert [e.tipo for e in restantes] == ["lluvia"]


def test_consulta_filtra_por_campo_y_suma(db, fake_llm):
    respuestas, _ = fake_llm
    u1 = _con_campo(db, "5491100000001", "Campo Uno")
    u2 = _con_campo(db, "5491100000002", "Campo Dos")

    def vacunacion(cant, lote):
        return {"intencion": "registrar", "eventos": [{
            "categoria": "sanidad", "tipo": "vacunacion", "cantidad_animales": cant,
            "categoria_animal": "vacas", "lote": lote, "fecha_evento": "2026-10-01",
        }]}

    respuestas["v1"] = vacunacion(20, "3")
    respuestas["v2"] = vacunacion(15, "lote 3")
    respuestas["v3"] = vacunacion(99, "3")
    bot.manejar_mensaje(db, u1.telefono, "v1", hoy=HOY)
    bot.manejar_mensaje(db, u1.telefono, "v2", hoy=HOY)
    bot.manejar_mensaje(db, u2.telefono, "v3", hoy=HOY)  # otro campo: no debe aparecer

    pregunta = "¿cuántas vacas se vacunaron en el lote 3 este mes?"
    respuestas[pregunta] = {
        "intencion": "consultar",
        "consulta": {"tipo": "vacunacion", "lote": "Lote 3", "categoria_animal": "vaca", "desde": "2026-10-01", "hasta": "2026-10-31"},
    }
    r = bot.manejar_mensaje(db, u1.telefono, pregunta, hoy=HOY)
    assert "*2 registros*" in r
    assert "Total vacunación: *35 animales*" in r
    assert "99" not in r


def test_firma_del_webhook(monkeypatch):
    monkeypatch.setattr(config, "META_APP_SECRET", "secreto")
    cuerpo = json.dumps({"entry": []}).encode()
    firma = "sha256=" + hmac.new(b"secreto", cuerpo, hashlib.sha256).hexdigest()
    assert whatsapp.firma_valida(cuerpo, firma)
    assert not whatsapp.firma_valida(cuerpo, "sha256=otra")
    assert not whatsapp.firma_valida(cuerpo, None)


def test_numero_argentino(monkeypatch):
    monkeypatch.setattr(config, "WA_AR_QUITAR_9", True)
    assert whatsapp.numero_para_envio("5492494123456") == "542494123456"
    assert whatsapp.numero_para_envio("34600000000") == "34600000000"


def test_eventos_del_mismo_mensaje_heredan_lote_y_categoria(db, fake_llm):
    """"ayer nacieron 4 terneros en el lote 5 y murió 1": la muerte también es del lote 5."""
    respuestas, _ = fake_llm
    usuario = _con_campo(db)
    texto = "ayer nacieron 4 terneros en el lote 5 y murió 1"
    respuestas[texto] = {
        "intencion": "registrar",
        "eventos": [
            {"categoria": "movimiento", "tipo": "nacimiento", "cantidad_animales": 4,
             "categoria_animal": "terneros", "lote": "5", "fecha_evento": "2026-10-08"},
            {"categoria": "movimiento", "tipo": "muerte", "cantidad_animales": 1,
             "fecha_evento": "2026-10-08", "confianza": "baja"},
        ],
    }
    r = bot.manejar_mensaje(db, usuario.telefono, texto, hoy=HOY)
    assert "Muerte · 1 ternero · lote 5 · 08/10/2026" in r

    muerte = db.scalar(select(Evento).where(Evento.tipo == "muerte"))
    assert muerte.lote == "5" and muerte.categoria_animal == "terneros"


def test_no_hereda_cuando_el_mensaje_tiene_varios_lotes(db, fake_llm):
    respuestas, _ = fake_llm
    usuario = _con_campo(db)
    respuestas["varios"] = {
        "intencion": "registrar",
        "eventos": [
            {"categoria": "movimiento", "tipo": "nacimiento", "cantidad_animales": 2, "lote": "3"},
            {"categoria": "movimiento", "tipo": "nacimiento", "cantidad_animales": 1, "lote": "7"},
            {"categoria": "movimiento", "tipo": "muerte", "cantidad_animales": 1},
        ],
    }
    bot.manejar_mensaje(db, usuario.telefono, "varios", hoy=HOY)
    muerte = db.scalar(select(Evento).where(Evento.tipo == "muerte"))
    assert muerte.lote is None


def test_la_lluvia_no_hereda_el_lote_de_los_animales(db, fake_llm):
    respuestas, _ = fake_llm
    usuario = _con_campo(db)
    respuestas["mixto"] = {
        "intencion": "registrar",
        "eventos": [
            {"categoria": "movimiento", "tipo": "nacimiento", "cantidad_animales": 4, "lote": "5"},
            {"categoria": "campo", "tipo": "lluvia", "valor": 35, "unidad": "mm"},
        ],
    }
    bot.manejar_mensaje(db, usuario.telefono, "mixto", hoy=HOY)
    lluvia = db.scalar(select(Evento).where(Evento.tipo == "lluvia"))
    assert lluvia.lote is None


def test_traslado_no_hereda_lote_de_origen(db, fake_llm):
    respuestas, _ = fake_llm
    usuario = _con_campo(db)
    respuestas["traslado"] = {
        "intencion": "registrar",
        "eventos": [
            {"categoria": "sanidad", "tipo": "vacunacion", "cantidad_animales": 10, "lote": "2"},
            {"categoria": "movimiento", "tipo": "traslado", "cantidad_animales": 50,
             "categoria_animal": "vaquillonas", "lote_destino": "5"},
        ],
    }
    bot.manejar_mensaje(db, usuario.telefono, "traslado", hoy=HOY)
    traslado = db.scalar(select(Evento).where(Evento.tipo == "traslado"))
    assert traslado.lote is None and traslado.lote_destino == "5"


def test_borrar_no_toca_mensajes_que_cayeron_en_el_mismo_timestamp(db, fake_llm):
    """El reloj de Windows salta cada ~15 ms: dos mensajes seguidos comparten `creado`."""
    respuestas, _ = fake_llm
    usuario = _con_campo(db)
    respuestas["uno"] = {"intencion": "registrar", "eventos": [
        {"categoria": "campo", "tipo": "lluvia", "valor": 10, "unidad": "mm"}]}
    respuestas["dos"] = {"intencion": "registrar", "eventos": [
        {"categoria": "movimiento", "tipo": "nacimiento", "cantidad_animales": 3,
         "categoria_animal": "terneros"}]}
    bot.manejar_mensaje(db, usuario.telefono, "uno", hoy=HOY)
    bot.manejar_mensaje(db, usuario.telefono, "dos", hoy=HOY)

    # Lo que pasaba en Windows: los dos mensajes con el mismo timestamp al milisegundo.
    mismo = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    for e in db.scalars(select(Evento)).all():
        e.creado = mismo
    db.flush()
    db.expire_all()  # sqlite no guarda el tzinfo: releemos para comparar lo que quedó

    eventos = db.scalars(select(Evento)).all()
    assert len({e.creado for e in eventos}) == 1          # mismo timestamp
    assert len({e.mensaje_id for e in eventos}) == 2      # distinto mensaje

    r = bot.manejar_mensaje(db, usuario.telefono, "borrar", hoy=HOY)
    assert "Nacimiento" in r and "Lluvia" not in r
    assert [e.tipo for e in db.scalars(select(Evento)).all()] == ["lluvia"]


def test_borrar_registro_viejo_sin_mensaje_id(db, fake_llm):
    """Filas de antes de la columna: se borra solo esa, no todas las que tengan NULL."""
    respuestas, _ = fake_llm
    usuario = _con_campo(db)
    for valor in (10, 20):
        db.add(Evento(campo_id=usuario.campo_id, usuario_id=usuario.id, categoria="campo",
                      tipo="lluvia", valor=valor, unidad="mm", fecha_evento=HOY, mensaje_id=None))
    db.flush()

    bot.manejar_mensaje(db, usuario.telefono, "borrar", hoy=HOY)
    assert [e.valor for e in db.scalars(select(Evento)).all()] == [10]
