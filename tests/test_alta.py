"""Alta por código de invitación: invitar, usar, anular, límite de intentos y altas vencidas."""

import re
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import main
from app.api import webhook
from app.canales import whatsapp
from app.ia import interprete
from app.infra.config import config
from app.infra.modelos import Auditoria, Cuenta, Evento, IntentoAlta, Invitacion, Solicitud, Usuario
from app.nucleo import acceso, alta, auditoria, invitaciones, perfil, pipeline, usuarios
from tests.ayudas import con_perfil, con_perfil_en

HOY = date(2026, 10, 15)
ADMIN, NUEVO, OTRO = "5492494000009", "5491100000001", "5491100000002"
FORMATO = re.compile(r"^CAMPO-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}$")


@pytest.fixture
def ia(monkeypatch):
    llamadas: list[str] = []

    def interpretar(texto, hoy, historial=None):
        llamadas.append(texto)
        return {"intencion": "saludo"}

    monkeypatch.setattr(interprete, "interpretar", interpretar)
    return llamadas


@pytest.fixture
def admin(db, monkeypatch):
    monkeypatch.setattr(config, "admin_telefonos", {ADMIN})
    return con_perfil(db, ADMIN)


def _mandar(db, texto, telefono=NUEVO):
    return pipeline.manejar_mensaje(db, telefono, texto, hoy=HOY)


def _invitar(db) -> str:
    respuesta = _mandar(db, "invitar", ADMIN)
    codigo = invitaciones.buscar_codigo(respuesta)
    assert codigo is not None
    return codigo


def _cuantos(db, modelo) -> int:
    return int(db.scalar(select(func.count()).select_from(modelo)) or 0)


def _adelantar(monkeypatch, **cuanto):
    momento = datetime.now(UTC) + timedelta(**cuanto)
    monkeypatch.setattr(alta, "_ahora", lambda: momento)


# --- Invitar ------------------------------------------------------------------


def test_invitar_da_un_codigo_dificil_de_adivinar_y_el_link(db, admin, monkeypatch):
    monkeypatch.setattr(config, "wa_numero_bot", "+54 9 249 400-0000")
    r = _mandar(db, "Invitar", ADMIN)
    codigo = invitaciones.buscar_codigo(r)
    assert codigo is not None and FORMATO.match(codigo)
    assert f"https://wa.me/5492494000000?text={codigo}" in r
    invitacion = db.scalar(select(Invitacion))
    vence = invitaciones.en_utc(invitacion.vence) - invitaciones.en_utc(invitacion.creado)
    assert vence == timedelta(days=7) and invitacion.creada_por == admin.id
    assert len({invitaciones.generar() for _ in range(200)}) == 200


def test_invitar_sin_el_numero_del_bot_da_solo_el_codigo(db, admin):
    r = _mandar(db, "invitar", ADMIN)
    assert "wa.me" not in r and "WA_NUMERO_BOT" in r


def test_solo_los_administradores_invitan(db, ia):
    con_perfil(db, OTRO)
    _mandar(db, "invitar", OTRO)
    assert ia == ["invitar"] and _cuantos(db, Invitacion) == 0


def test_invitaciones_lista_las_vigentes_y_las_altas_sin_terminar(db, admin):
    vigente, usada, anulada = _invitar(db), _invitar(db), _invitar(db)
    _mandar(db, usada)
    _mandar(db, f"anular {anulada}", ADMIN)
    r = _mandar(db, "invitaciones", ADMIN)
    assert vigente in r and usada not in r and anulada not in r
    assert "Altas sin terminar: 1" in r


def test_anular(db, admin):
    codigo = _invitar(db)
    assert "anulé" in _mandar(db, f"anular {codigo.lower()}", ADMIN)
    assert "ya estaba anulado" in _mandar(db, f"anular {codigo}", ADMIN)
    assert _mandar(db, codigo) == alta.CODIGO_INVALIDO
    usado = _invitar(db)
    _mandar(db, usado, OTRO)
    assert "ya se usó" in _mandar(db, f"anular {usado}", ADMIN)
    assert "No encontré" in _mandar(db, "anular CAMPO-AAAA-AAAA", ADMIN)
    assert "No entendí" in _mandar(db, "anular algo", ADMIN)


# --- Sin código -----------------------------------------------------------------


def test_sin_codigo_mensaje_fijo_sin_ia_y_sin_guardar_nada(db, ia):
    assert _mandar(db, "hola, quiero usar el bot") == acceso.NO_AUTORIZADO
    assert "prueba privada" in acceso.NO_AUTORIZADO
    assert ia == []
    for modelo in (Usuario, Cuenta, Solicitud, IntentoAlta):
        assert _cuantos(db, modelo) == 0, modelo


# --- Alta con código ------------------------------------------------------------


def test_alta_completa_con_el_codigo_del_link(db, admin, ia):
    codigo = _invitar(db)
    r = _mandar(db, codigo)
    assert "bienvenida a CampoBot" in r and "3 datos tuyos" in r and perfil.PREGUNTAS["nombre"] in r
    u = db.scalar(select(Usuario).where(Usuario.telefono == NUEVO))
    assert not u.autorizado
    solicitud = db.scalar(select(Solicitud).where(Solicitud.usuario_id == u.id))
    assert (solicitud.origen, solicitud.estado) == (usuarios.POR_CODIGO, usuarios.PENDIENTE)

    _mandar(db, "Pedro Ramírez")
    _mandar(db, "3")
    r = _mandar(db, "azul")
    assert "¡Listo, Pedro! Ya podés usar CampoBot." in r
    assert u.autorizado and u.rubro == "productor" and u.localidad == "Azul"
    assert (solicitud.estado, solicitud.resuelto is not None) == (usuarios.APROBADA, True)
    alta_registrada = db.scalar(select(Auditoria).where(Auditoria.accion == auditoria.ALTA))
    assert alta_registrada.sobre == u.id
    assert ia == []

    _mandar(db, "llovieron 20 mm")
    assert ia == ["llovieron 20 mm"]


def test_el_codigo_sirve_escrito_de_otra_forma_y_con_texto_alrededor(db, admin):
    codigo = _invitar(db)
    escrito = codigo.lower().replace("-", " ")
    assert "bienvenida" in _mandar(db, f"hola! me pasaron este código: {escrito}")


def test_el_codigo_es_de_una_sola_persona(db, admin):
    codigo = _invitar(db)
    _mandar(db, codigo, NUEVO)
    assert _mandar(db, codigo, OTRO) == alta.CODIGO_INVALIDO
    assert db.scalar(select(Usuario).where(Usuario.telefono == OTRO)) is None
    assert invitaciones.tomar(db, codigo, datetime.now(UTC)) is None  # ni aunque llegue a la vez


def test_un_codigo_vencido_no_sirve(db, admin, monkeypatch):
    codigo = _invitar(db)
    _adelantar(monkeypatch, days=7, minutes=1)
    assert _mandar(db, codigo) == alta.CODIGO_INVALIDO


def test_durante_el_alta_funcionan_ayuda_y_borrar_mis_datos(db, admin, ia):
    _mandar(db, _invitar(db))
    r = _mandar(db, "ayuda")
    assert "CAMPOBOT" in r and perfil.PREGUNTAS["nombre"] in r
    _mandar(db, "borrar mis datos")
    assert "DATOS BORRADOS" in _mandar(db, "confirmo borrar mis datos")
    assert db.scalar(select(Usuario).where(Usuario.telefono == NUEVO)) is None
    assert ia == []


def test_quien_ya_tiene_acceso_y_manda_un_codigo_no_lo_gasta(db, admin, ia):
    codigo = _invitar(db)
    con_perfil(db, NUEVO)
    assert _mandar(db, codigo) == alta.YA_TENES_ACCESO
    assert db.scalar(select(Invitacion)).usada is None
    assert ia == []


def test_a_quien_le_sacaron_el_acceso_vuelve_con_un_codigo_y_conserva_lo_suyo(db, admin):
    u = con_perfil(db, NUEVO)
    db.add(Evento(cuenta_id=u.cuenta_id, usuario_id=u.id, categoria="campo", tipo="lluvia", fecha_evento=HOY))
    usuarios.quitar(db, NUEVO)
    assert _mandar(db, "hola") == acceso.NO_AUTORIZADO
    assert "Hola de nuevo, Juana" in _mandar(db, _invitar(db))
    assert u.autorizado and _cuantos(db, Evento) == 1


# --- Intentos fallidos ----------------------------------------------------------


def test_cinco_codigos_equivocados_bloquean_sin_avisar(db, admin, monkeypatch):
    for _ in range(alta.MAX_INTENTOS):
        assert _mandar(db, "CAMPO-AAAA-AAAA") == alta.CODIGO_INVALIDO
    codigo = _invitar(db)
    assert _mandar(db, codigo) == alta.CODIGO_INVALIDO  # bloqueado: la misma respuesta
    assert db.scalar(select(Invitacion).where(Invitacion.codigo == codigo)).usada is None  # no se gastó

    intento = db.scalar(select(IntentoAlta))
    assert NUEVO not in intento.telefono_hash and len(intento.telefono_hash) == 64
    assert _cuantos(db, Usuario) == 1  # solo el admin: del que prueba no se guarda nada

    _adelantar(monkeypatch, hours=24, minutes=1)
    assert "bienvenida" in _mandar(db, codigo)
    assert _cuantos(db, IntentoAlta) == 0  # los intentos viejos se borran


def test_los_intentos_son_por_numero(db, admin):
    for _ in range(alta.MAX_INTENTOS):
        _mandar(db, "CAMPO-AAAA-AAAA", OTRO)
    assert "bienvenida" in _mandar(db, _invitar(db), NUEVO)


def test_el_hash_depende_de_la_clave(monkeypatch):
    sin_clave = alta._hash(NUEVO)
    monkeypatch.setattr(config, "clave_hash", "otra-clave")
    assert alta._hash(NUEVO) != sin_clave


# --- Altas sin terminar -----------------------------------------------------------


def test_el_alta_se_puede_retomar_durante_7_dias_y_despues_se_borra(db, admin, monkeypatch):
    codigo = _invitar(db)
    _mandar(db, codigo)
    _mandar(db, "Pedro Ramírez")

    _adelantar(monkeypatch, days=6)
    assert perfil.PREGUNTAS["localidad"] in _mandar(db, "1")  # retoma donde quedó

    _adelantar(monkeypatch, days=7, minutes=1)
    assert _mandar(db, "Azul") == acceso.NO_AUTORIZADO
    assert db.scalar(select(Usuario).where(Usuario.telefono == NUEVO)) is None
    assert _cuantos(db, Solicitud) == 1  # solo la del admin de prueba
    assert _cuantos(db, Cuenta) == 1
    assert db.scalar(select(Invitacion)).usada is not None  # el código queda gastado
    assert _mandar(db, codigo) == alta.CODIGO_INVALIDO
    assert db.scalar(select(Auditoria).where(Auditoria.accion == auditoria.ALTA_VENCIDA)) is not None


# --- Por el webhook -----------------------------------------------------------------


def test_un_audio_durante_el_alta_pide_responder_por_escrito(servidor, motor, monkeypatch):
    monkeypatch.setattr(config, "admin_telefonos", {ADMIN})
    con_perfil_en(motor, ADMIN)

    def no_llamar(*_):
        raise AssertionError("no debería transcribir")

    monkeypatch.setattr(whatsapp, "descargar_media", no_llamar)
    monkeypatch.setattr(interprete, "transcribir", no_llamar)

    def mensaje(wamid: str, **contenido) -> dict:
        return {"entry": [{"changes": [{"value": {"messages": [{"from": NUEVO, "id": wamid, **contenido}]}}]}]}

    with TestClient(main.app) as c:
        c.post("/webhook", json={"entry": [{"changes": [{"value": {"messages": [
            {"from": ADMIN, "id": "wamid.i", "type": "text", "text": {"body": "invitar"}}
        ]}}]}]})  # fmt: skip
        assert webhook.fila.esperar(5)
        codigo = invitaciones.buscar_codigo(servidor[-1][1])
        c.post("/webhook", json=mensaje("wamid.c", type="text", text={"body": codigo}))
        c.post("/webhook", json=mensaje("wamid.a", type="audio", audio={"id": "media1"}))
        assert webhook.fila.esperar(5)
    assert "bienvenida" in servidor[-2][1]
    assert servidor[-1] == (NUEVO, alta.POR_ESCRITO)
