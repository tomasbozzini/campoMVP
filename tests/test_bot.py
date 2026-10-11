import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import bot, config, llm, usuarios, whatsapp
from app.db import Base
from app.models import BorradoPendiente, Evento, MensajeChat, Usuario

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

    def interpretar(texto, hoy, historial=None):
        llamadas.append(texto)
        return respuestas[texto]

    monkeypatch.setattr(llm, "interpretar", interpretar)
    return respuestas, llamadas


def _con_campo(db, telefono="5492494000001"):
    """Un usuario autorizado, con su cuaderno vacío."""
    return usuarios.autorizar(db, telefono)


def test_numero_sin_acceso_no_usa_el_bot(db, fake_llm):
    _, llamadas = fake_llm
    assert bot.manejar_mensaje(db, "5491100000000", "hola", hoy=HOY) == bot.NO_AUTORIZADO
    assert llamadas == []
    assert db.scalar(select(Usuario)) is None  # no se guarda nada de números desconocidos


def test_admin_autoriza_y_quita_por_whatsapp(db, fake_llm, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TELEFONOS", {"5492494000009"})
    admin = "5492494000009"
    assert "autorizar" in bot.manejar_mensaje(db, admin, "ayuda", hoy=HOY)

    # Meta guarda los números argentinos sin el 9: igual tiene que reconocerlo.
    r = bot.manejar_mensaje(db, admin, "autorizar +54 249 412-3456", hoy=HOY)
    assert "5492494123456 ya puede usar" in r
    assert "Tu asistente" in bot.manejar_mensaje(db, "5492494123456", "ayuda", hoy=HOY)
    assert "autorizar" not in bot.manejar_mensaje(db, "5492494123456", "ayuda", hoy=HOY)
    assert "5492494123456" in bot.manejar_mensaje(db, admin, "autorizados", hoy=HOY)

    assert "saqué el acceso" in bot.manejar_mensaje(db, admin, "quitar 5492494123456", hoy=HOY)
    assert bot.manejar_mensaje(db, "5492494123456", "ayuda", hoy=HOY) == bot.NO_AUTORIZADO


def test_un_no_admin_no_puede_autorizar(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    respuestas["autorizar 5491100000005"] = {"intencion": "fuera_de_alcance"}
    assert bot.manejar_mensaje(db, u.telefono, "autorizar 5491100000005", hoy=HOY) == bot.FUERA_DE_ALCANCE
    assert not bot.puede_usar_ia(db, "5491100000005")


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
    assert evento.usuario_id == usuario.id
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


def test_consulta_solo_ve_lo_propio_y_suma(db, fake_llm):
    respuestas, _ = fake_llm
    u1 = _con_campo(db, "5491100000001")
    u2 = _con_campo(db, "5491100000002")

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
    bot.manejar_mensaje(db, u2.telefono, "v3", hoy=HOY)  # otra persona: no debe aparecer

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
        db.add(Evento(usuario_id=usuario.id, categoria="campo",
                      tipo="lluvia", valor=valor, unidad="mm", fecha_evento=HOY, mensaje_id=None))
    db.flush()

    bot.manejar_mensaje(db, usuario.telefono, "borrar", hoy=HOY)
    assert [e.valor for e in db.scalars(select(Evento)).all()] == [10]


def test_veterinario_recorre_varios_campos(db, fake_llm):
    """El establecimiento nombrado queda como actual para lo que se anote después."""
    respuestas, _ = fake_llm
    vet = _con_campo(db, "5491100000007")
    vacunacion = {"categoria": "sanidad", "tipo": "vacunacion", "cantidad_animales": 20, "categoria_animal": "vacas"}
    respuestas["estoy en La Esperanza"] = {"intencion": "establecimiento", "establecimiento": "La Esperanza"}
    respuestas["vacuné 20 vacas"] = {"intencion": "registrar", "eventos": [vacunacion]}
    respuestas["en El Ombú hice tacto a 50 vaquillonas"] = {
        "intencion": "registrar", "establecimiento": "El Ombú",
        "eventos": [{"categoria": "reproduccion", "tipo": "tacto", "cantidad_animales": 50, "categoria_animal": "vaquillonas"}],
    }
    respuestas["y vacuné 20 vacas"] = {"intencion": "registrar", "eventos": [vacunacion]}

    assert "La Esperanza" in bot.manejar_mensaje(db, vet.telefono, "estoy en La Esperanza", hoy=HOY)
    assert "Anotado en 📍 *La Esperanza*" in bot.manejar_mensaje(db, vet.telefono, "vacuné 20 vacas", hoy=HOY)
    assert "Anotado en 📍 *El Ombú*" in bot.manejar_mensaje(db, vet.telefono, "en El Ombú hice tacto a 50 vaquillonas", hoy=HOY)
    assert "Anotado en 📍 *El Ombú*" in bot.manejar_mensaje(db, vet.telefono, "y vacuné 20 vacas", hoy=HOY)

    # Consulta por establecimiento, escrito distinto ("estancia", minúsculas, sin tilde).
    respuestas["¿qué hice en la estancia el ombu?"] = {
        "intencion": "consultar", "consulta": {"establecimiento": "estancia el ombu"}}
    r = bot.manejar_mensaje(db, vet.telefono, "¿qué hice en la estancia el ombu?", hoy=HOY)
    assert "*2 registros*" in r and "Tacto" in r and "📍 El Ombú" in r and "La Esperanza" not in r


def test_sin_establecimiento_lo_aclara(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    respuestas["llovieron 30 mm"] = {"intencion": "registrar", "eventos": [
        {"categoria": "campo", "tipo": "lluvia", "valor": 30, "unidad": "mm"}]}
    assert "Anotado (sin establecimiento)" in bot.manejar_mensaje(db, u.telefono, "llovieron 30 mm", hoy=HOY)


def test_el_dueno_no_ve_lo_que_anoto_el_veterinario(db, fake_llm):
    """Mismo establecimiento, cuadernos separados."""
    respuestas, _ = fake_llm
    vet = _con_campo(db, "5491100000007")
    dueno = _con_campo(db, "5491100000008")
    respuestas["en La Esperanza vacuné 20 vacas"] = {
        "intencion": "registrar", "establecimiento": "La Esperanza",
        "eventos": [{"categoria": "sanidad", "tipo": "vacunacion", "cantidad_animales": 20}]}
    bot.manejar_mensaje(db, vet.telefono, "en La Esperanza vacuné 20 vacas", hoy=HOY)

    respuestas["¿qué pasó en La Esperanza?"] = {"intencion": "consultar", "consulta": {"establecimiento": "La Esperanza"}}
    assert bot.manejar_mensaje(db, dueno.telefono, "¿qué pasó en La Esperanza?", hoy=HOY) == "No encontré registros para esa consulta."
    # y "borrar" del dueño no toca lo del veterinario
    assert "nada anotado" in bot.manejar_mensaje(db, dueno.telefono, "borrar", hoy=HOY)
    assert db.scalar(select(Evento)) is not None


def _vacunar_vaquillonas(respuestas, db, usuario):
    respuestas["vacuné 5 vaquillonas en el lote 3"] = {"intencion": "registrar", "eventos": [
        {"categoria": "sanidad", "tipo": "vacunacion", "cantidad_animales": 5,
         "categoria_animal": "vaquillonas", "lote": "3"}]}
    bot.manejar_mensaje(db, usuario.telefono, "vacuné 5 vaquillonas en el lote 3", hoy=HOY)


def test_corregir_completa_el_registro_en_vez_de_crear_otro(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    _vacunar_vaquillonas(respuestas, db, u)
    texto = "a esas 5 vaquillonas las vacuné con ivermectina"
    respuestas[texto] = {"intencion": "corregir", "correccion": {
        "referencia": {"cantidad_animales": 5, "categoria_animal": "vaquillonas"},
        "cambios": {"producto": "ivermectina"}}}

    r = bot.manejar_mensaje(db, u.telefono, texto, hoy=HOY)
    assert "Antes: Vacunación · 5 vaquillonas · lote 3" in r
    assert "Ahora: Vacunación (ivermectina) · 5 vaquillonas · lote 3" in r
    eventos = db.scalars(select(Evento)).all()
    assert len(eventos) == 1 and eventos[0].producto == "ivermectina"


def test_corregir_busca_el_registro_que_coincide(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    _vacunar_vaquillonas(respuestas, db, u)
    respuestas["llovieron 20 mm"] = {"intencion": "registrar", "eventos": [
        {"categoria": "campo", "tipo": "lluvia", "valor": 20, "unidad": "mm"}]}
    bot.manejar_mensaje(db, u.telefono, "llovieron 20 mm", hoy=HOY)

    # se refiere a las vaquillonas, aunque lo último que anotó fue la lluvia
    respuestas["no eran 5 vaquillonas, eran 7"] = {"intencion": "corregir", "correccion": {
        "referencia": {"cantidad_animales": 5, "categoria_animal": "vaquillona"},
        "cambios": {"cantidad_animales": 7}}}
    bot.manejar_mensaje(db, u.telefono, "no eran 5 vaquillonas, eran 7", hoy=HOY)
    vacunacion = db.scalar(select(Evento).where(Evento.tipo == "vacunacion"))
    lluvia = db.scalar(select(Evento).where(Evento.tipo == "lluvia"))
    assert vacunacion.cantidad_animales == 7 and lluvia.valor == 20


def test_corregir_sin_referencia_toma_el_ultimo_y_no_toca_otros_usuarios(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db, "5491100000001")
    otro = _con_campo(db, "5491100000002")
    _vacunar_vaquillonas(respuestas, db, otro)
    respuestas["lo de recién fue en el lote 4"] = {"intencion": "corregir", "correccion": {
        "referencia": {}, "cambios": {"lote": "lote 4"}}}

    r = bot.manejar_mensaje(db, u.telefono, "lo de recién fue en el lote 4", hoy=HOY)
    assert "No encontré cuál de tus registros" in r
    assert db.scalar(select(Evento)).lote == "3"  # el registro del otro usuario no se tocó

    _vacunar_vaquillonas(respuestas, db, u)
    bot.manejar_mensaje(db, u.telefono, "lo de recién fue en el lote 4", hoy=HOY)
    mio = db.scalar(select(Evento).where(Evento.usuario_id == u.id))
    assert mio.lote == "4"


def test_corregir_no_acepta_fechas_futuras_ni_campos_raros(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    _vacunar_vaquillonas(respuestas, db, u)
    respuestas["x"] = {"intencion": "corregir", "correccion": {
        "referencia": {}, "cambios": {"fecha_evento": "2030-01-01", "usuario_id": 999}}}
    bot.manejar_mensaje(db, u.telefono, "x", hoy=HOY)
    e = db.scalar(select(Evento))
    assert e.fecha_evento == HOY and e.usuario_id == u.id


def _anotar_en_la_pastora(respuestas, db, u):
    respuestas["varios"] = {"intencion": "registrar", "establecimiento": "La Pastora", "eventos": [
        {"categoria": "sanidad", "tipo": "vacunacion", "cantidad_animales": 5, "categoria_animal": "vaquillonas", "lote": "3"},
        {"categoria": "campo", "tipo": "cosecha", "lote": "5", "valor": 40, "unidad": "ha"},
        {"categoria": "campo", "tipo": "lluvia", "valor": 30, "unidad": "mm"},
    ]}
    bot.manejar_mensaje(db, u.telefono, "varios", hoy=HOY)
    respuestas["llovio en el ombu"] = {"intencion": "registrar", "establecimiento": "El Ombú", "eventos": [
        {"categoria": "campo", "tipo": "lluvia", "valor": 12, "unidad": "mm"}]}
    bot.manejar_mensaje(db, u.telefono, "llovio en el ombu", hoy=HOY)


def test_borrar_registros_puntuales(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    _anotar_en_la_pastora(respuestas, db, u)
    texto = "borrá las 5 vaquillonas y la cosecha del lote 5, ambos de La Pastora"
    respuestas[texto] = {"intencion": "borrar", "borrado": {"registros": [
        {"cantidad_animales": 5, "categoria_animal": "vaquillonas", "establecimiento": "La Pastora"},
        {"tipo": "cosecha", "lote": "5", "establecimiento": "la pastora"},
    ]}}
    r = bot.manejar_mensaje(db, u.telefono, texto, hoy=HOY)
    assert "Borré:" in r and "Vacunación · 5 vaquillonas" in r and "Cosecha" in r
    assert sorted(e.valor for e in db.scalars(select(Evento)).all()) == [12, 30]  # quedan las lluvias


def test_borrar_la_lluvia_de_la_pastora(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    _anotar_en_la_pastora(respuestas, db, u)
    respuestas["borrá la lluvia de la pastora"] = {"intencion": "borrar", "borrado": {"registros": [
        {"tipo": "lluvia", "establecimiento": "La Pastora"}]}}
    r = bot.manejar_mensaje(db, u.telefono, "borrá la lluvia de la pastora", hoy=HOY)
    assert "Borré:" in r and "La Pastora" in r
    lluvias = db.scalars(select(Evento).where(Evento.tipo == "lluvia")).all()
    assert [e.establecimiento for e in lluvias] == ["El Ombú"]


def test_borrar_ambiguo_no_borra_y_muestra_opciones(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    _anotar_en_la_pastora(respuestas, db, u)
    respuestas["borrá la lluvia"] = {"intencion": "borrar", "borrado": {"registros": [{"tipo": "lluvia"}]}}
    r = bot.manejar_mensaje(db, u.telefono, "borrá la lluvia", hoy=HOY)
    assert "Hay 2 registros" in r and "no borré ninguno" in r and "El Ombú" in r and "La Pastora" in r
    assert len(db.scalars(select(Evento)).all()) == 4

    respuestas["borrá todas las lluvias"] = {"intencion": "borrar", "borrado": {"registros": [
        {"tipo": "lluvia", "todos": True}]}}
    bot.manejar_mensaje(db, u.telefono, "borrá todas las lluvias", hoy=HOY)
    assert db.scalar(select(Evento).where(Evento.tipo == "lluvia")) is None


def test_borrar_no_encontrado_y_ajeno(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db, "5491100000001")
    otro = _con_campo(db, "5491100000002")
    _anotar_en_la_pastora(respuestas, db, otro)
    respuestas["borrá la cosecha de La Pastora"] = {"intencion": "borrar", "borrado": {"registros": [
        {"tipo": "cosecha", "establecimiento": "La Pastora"}]}}
    r = bot.manejar_mensaje(db, u.telefono, "borrá la cosecha de La Pastora", hoy=HOY)
    assert "No encontré" in r
    assert len(db.scalars(select(Evento)).all()) == 4  # lo del otro usuario sigue intacto


def test_lista_de_lo_anotado(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    _anotar_en_la_pastora(respuestas, db, u)
    respuestas["¿qué tengo anotado en La Pastora?"] = {"intencion": "consultar", "consulta": {"establecimiento": "La Pastora"}}
    r = bot.manejar_mensaje(db, u.telefono, "¿qué tengo anotado en La Pastora?", hoy=HOY)
    assert "*3 registros*" in r and "Cosecha" in r and "El Ombú" not in r


def test_reintenta_el_numero_argentino_sin_el_9(monkeypatch):
    enviados = []

    class Resp:
        def __init__(self, status, cuerpo):
            self.status_code, self._cuerpo, self.text = status, cuerpo, json.dumps(cuerpo)

        def json(self):
            return self._cuerpo

    def post(url, headers, json, timeout):
        enviados.append(json["to"])
        if json["to"] == "5492494123456":
            return Resp(400, {"error": {"code": 131030}})
        return Resp(200, {})

    monkeypatch.setattr(config, "WA_AR_QUITAR_9", False)
    monkeypatch.setattr(whatsapp.httpx, "post", post)
    whatsapp.enviar_texto("5492494123456", "hola")
    whatsapp.enviar_texto("5492494123456", "chau")
    assert enviados == ["5492494123456", "542494123456", "5492494123456", "542494123456"]


def test_la_ia_recibe_la_charla_reciente_solo_del_mismo_usuario(db, monkeypatch):
    vistos = {}
    respuestas = {
        "vacuné 5 vaquillonas": {"intencion": "aclarar", "falta": ["establecimiento"]},
        "La Pastora": {"intencion": "registrar", "establecimiento": "La Pastora", "eventos": [
            {"categoria": "sanidad", "tipo": "vacunacion", "cantidad_animales": 5, "categoria_animal": "vaquillonas"}]},
        "hola": {"intencion": "saludo"},
    }

    def interpretar(texto, hoy, historial=None):
        vistos[texto] = historial
        return respuestas[texto]

    monkeypatch.setattr(llm, "interpretar", interpretar)
    u = _con_campo(db, "5491100000001")
    otro = _con_campo(db, "5491100000002")
    bot.manejar_mensaje(db, otro.telefono, "hola", hoy=HOY)

    assert bot.manejar_mensaje(db, u.telefono, "vacuné 5 vaquillonas", hoy=HOY) == bot.PREGUNTAS["establecimiento"]
    assert "Anotado en 📍 *La Pastora*" in bot.manejar_mensaje(db, u.telefono, "La Pastora", hoy=HOY)
    assert vistos["La Pastora"] == [
        ("usuario", "vacuné 5 vaquillonas"), ("bot", bot.PREGUNTAS["establecimiento"])]
    assert vistos["vacuné 5 vaquillonas"] == []  # no ve lo que charló el otro usuario


def test_la_charla_vieja_no_se_usa_y_no_se_acumula(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    respuestas["hola"] = {"intencion": "saludo"}
    for _ in range(bot.HISTORIAL_MENSAJES + 5):
        bot.manejar_mensaje(db, u.telefono, "hola", hoy=HOY)
    assert len(db.scalars(select(MensajeChat)).all()) == bot.HISTORIAL_MENSAJES * 2

    for m in db.scalars(select(MensajeChat)).all():
        m.creado = datetime.now(timezone.utc) - timedelta(minutes=bot.HISTORIAL_MINUTOS + 1)
    db.flush()
    assert bot._historial(db, u) == []


def _cinco_en_la_pastora(respuestas, db, u):
    respuestas["cinco"] = {"intencion": "registrar", "establecimiento": "La Pastora", "eventos": [
        {"categoria": "campo", "tipo": "lluvia", "valor": v, "unidad": "mm"} for v in (1, 2, 3, 4, 5)]}
    bot.manejar_mensaje(db, u.telefono, "cinco", hoy=HOY)
    respuestas["en el ombu"] = {"intencion": "registrar", "establecimiento": "El Ombú", "eventos": [
        {"categoria": "campo", "tipo": "lluvia", "valor": 99, "unidad": "mm"}]}
    bot.manejar_mensaje(db, u.telefono, "en el ombu", hoy=HOY)


def test_borrar_todo_lo_de_la_lista_pide_confirmacion(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    _cinco_en_la_pastora(respuestas, db, u)
    respuestas["borrá todo de la lista"] = {"intencion": "borrar", "borrado": {"registros": [
        {"establecimiento": "La Pastora", "todos": True}]}}

    r = bot.manejar_mensaje(db, u.telefono, "borrá todo de la lista", hoy=HOY)
    assert "Voy a borrar *5 registros*" in r and "¿Confirmás?" in r
    assert len(db.scalars(select(Evento)).all()) == 6  # todavía no borró nada

    assert "borré 5 registros" in bot.manejar_mensaje(db, u.telefono, "Sí", hoy=HOY)
    assert [e.valor for e in db.scalars(select(Evento)).all()] == [99]


def test_borrar_todo_se_puede_cancelar_o_se_descarta(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    _cinco_en_la_pastora(respuestas, db, u)
    respuestas["borrá todo"] = {"intencion": "borrar", "borrado": {"registros": [{"todos": True}]}}

    assert "Voy a borrar *6 registros*" in bot.manejar_mensaje(db, u.telefono, "borrá todo", hoy=HOY)
    assert bot.manejar_mensaje(db, u.telefono, "no", hoy=HOY) == "Listo, no borré nada."
    assert len(db.scalars(select(Evento)).all()) == 6

    # Otro mensaje en el medio descarta el pendiente: un "sí" posterior no borra.
    bot.manejar_mensaje(db, u.telefono, "borrá todo", hoy=HOY)
    respuestas["hola"] = {"intencion": "saludo"}
    bot.manejar_mensaje(db, u.telefono, "hola", hoy=HOY)
    respuestas["sí"] = {"intencion": "saludo"}
    bot.manejar_mensaje(db, u.telefono, "sí", hoy=HOY)
    assert len(db.scalars(select(Evento)).all()) == 6


def test_confirmacion_vencida_no_borra(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db)
    _cinco_en_la_pastora(respuestas, db, u)
    respuestas["borrá todo"] = {"intencion": "borrar", "borrado": {"registros": [{"todos": True}]}}
    bot.manejar_mensaje(db, u.telefono, "borrá todo", hoy=HOY)
    pendiente = db.get(BorradoPendiente, u.id)
    pendiente.creado = datetime.now(timezone.utc) - timedelta(minutes=bot.CONFIRMAR_MINUTOS + 1)
    db.flush()
    assert "no borré nada" in bot.manejar_mensaje(db, u.telefono, "sí", hoy=HOY)
    assert len(db.scalars(select(Evento)).all()) == 6


def test_confirmacion_no_borra_lo_de_otro(db, fake_llm):
    respuestas, _ = fake_llm
    u = _con_campo(db, "5491100000001")
    otro = _con_campo(db, "5491100000002")
    _cinco_en_la_pastora(respuestas, db, otro)
    ids_del_otro = [e.id for e in db.scalars(select(Evento)).all()]
    db.add(BorradoPendiente(usuario_id=u.id, ids=ids_del_otro))  # ids ajenos, por si acaso
    db.flush()
    bot.manejar_mensaje(db, u.telefono, "sí", hoy=HOY)
    assert len(db.scalars(select(Evento)).all()) == 6
