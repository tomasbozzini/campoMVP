"""Sesiones de trabajo: apertura, registros que van a la sesión, cierre y resumen.

Las reglas son las de docs/arquitectura.md, decisiones de producto "Sesiones" y "Campo actual".
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ia import interprete
from app.infra.modelos import Evento, Sesion
from app.nucleo import pipeline, sesiones
from tests.ayudas import con_perfil

HOY = date(2026, 10, 15)
TEL, OTRO = "5491100000001", "5491100000002"
INICIO = datetime(2026, 10, 15, 11, 0, tzinfo=UTC)  # 08:00 en Argentina


@pytest.fixture
def reloj(monkeypatch):
    """La hora que ve el pipeline; se adelanta con reloj.pasar(horas=...)."""

    class Reloj:
        ahora = INICIO

        def pasar(self, **cuanto):
            self.ahora += timedelta(**cuanto)

    r = Reloj()
    monkeypatch.setattr(pipeline, "_ahora", lambda: r.ahora)
    return r


@pytest.fixture
def ia(monkeypatch):
    """La IA falsa: cada texto tiene su respuesta (una acción o varias). Anota los textos que le llegaron."""
    respuestas: dict[str, dict] = {
        "arranco manga en el retiro lote 3": {
            "intencion": "abrir_sesion",
            "establecimiento": "El Retiro",
            "sesion": {"lote": "lote 3", "actividad": "manga"},
        },
        "terminamos": {"intencion": "cerrar_sesion"},
        "estoy en el ombú": {"intencion": "establecimiento", "establecimiento": "El Ombú"},
        "vacuné 30 vaquillonas": _registro(tipo="vacunacion", cantidad_animales=30, categoria_animal="vaquillonas"),
        "desparasité 20 terneros": _registro(tipo="desparasitacion", cantidad_animales=20, categoria_animal="terneros"),
        "llovieron 15 mm": _registro(categoria="campo", tipo="lluvia", valor=15, unidad="mm"),
        "en el lote 7 vacuné 5 toros": _registro(tipo="vacunacion", cantidad_animales=5, lote="7"),
        "en el ombú vacuné 10 vacas": _registro("El Ombú", tipo="vacunacion", cantidad_animales=10),
    }
    llamadas: list[str] = []

    def interpretar(texto, hoy, historial=None, partes=(), pregunta=None):
        llamadas.append(texto)
        return respuestas[texto]

    monkeypatch.setattr(interprete, "interpretar", interpretar)
    return respuestas, llamadas


def _registro(establecimiento=None, categoria="sanidad", **evento):
    return {
        "intencion": "registrar",
        "establecimiento": establecimiento,
        "eventos": [{"categoria": categoria, **evento}],
    }


def _mandar(db, texto, telefono=TEL):
    return pipeline.manejar_mensaje(db, telefono, texto, hoy=HOY)


def _ultimo(db: Session) -> Evento:
    return db.scalars(select(Evento).order_by(Evento.id.desc()).limit(1)).one()


def _abiertas(db) -> list[Sesion]:
    return list(db.scalars(select(Sesion).where(Sesion.cerrada.is_(None))).all())


def test_abrir_una_sesion_con_campo_lote_y_actividad(db, ia, reloj):
    u = con_perfil(db, TEL)
    r = _mandar(db, "arranco manga en el retiro lote 3")
    assert "▶️ *SESIÓN ABIERTA*\n📍 El Retiro · Lote 3 · Manga" in r
    assert "queda en esta sesión, en el lote 3" in r
    assert u.establecimiento_actual is not None and u.establecimiento_actual.nombre == "El Retiro"


def test_lo_que_no_nombra_campo_va_a_la_sesion_con_su_lote(db, ia, reloj):
    con_perfil(db, TEL)
    _mandar(db, "arranco manga en el retiro lote 3")
    sesion = _abiertas(db)[0]

    assert "📍 El Retiro · 1 registro · ▶️ en la sesión" in _mandar(db, "vacuné 30 vaquillonas")
    vacunacion = _ultimo(db)
    assert (vacunacion.sesion_id, vacunacion.nombre_establecimiento, vacunacion.nombre_lote) == (
        sesion.id,
        "El Retiro",
        "3",
    )
    _mandar(db, "llovieron 15 mm")
    assert (_ultimo(db).sesion_id, _ultimo(db).nombre_lote) == (sesion.id, None)  # la lluvia es del campo
    _mandar(db, "en el lote 7 vacuné 5 toros")
    assert (_ultimo(db).sesion_id, _ultimo(db).nombre_lote) == (sesion.id, "7")  # su lote, en el campo de la sesión
    lote = _ultimo(db).lote
    assert lote is not None and lote.establecimiento_id == sesion.establecimiento_id


def test_un_registro_de_otro_campo_queda_fuera_con_aviso(db, ia, reloj):
    u = con_perfil(db, TEL)
    _mandar(db, "arranco manga en el retiro lote 3")
    sesion = _abiertas(db)[0]

    r = _mandar(db, "en el ombú vacuné 10 vacas")
    assert "Quedó en *El Ombú*, fuera de la sesión abierta (📍 El Retiro · Lote 3 · Manga)" in r
    assert "▶️ en la sesión" not in r
    assert (_ultimo(db).sesion_id, _ultimo(db).nombre_establecimiento) == (None, "El Ombú")

    _mandar(db, "vacuné 30 vaquillonas")  # los siguientes sin campo siguen yendo a la sesión
    assert (_ultimo(db).sesion_id, _ultimo(db).nombre_establecimiento) == (sesion.id, "El Retiro")

    # El Ombú quedó como el último campo nombrado: sin sesión, lo que no nombra campo va ahí.
    _mandar(db, "terminamos")
    assert u.establecimiento_actual is not None and u.establecimiento_actual.nombre == "El Ombú"
    _mandar(db, "vacuné 30 vaquillonas")
    assert (_ultimo(db).sesion_id, _ultimo(db).nombre_establecimiento) == (None, "El Ombú")


def test_estoy_en_otro_campo_avisa_que_la_sesion_sigue_abierta(db, ia, reloj):
    con_perfil(db, TEL)
    _mandar(db, "arranco manga en el retiro lote 3")
    r = _mandar(db, "estoy en el ombú")
    assert "Tenés abierta una sesión (📍 El Retiro · Lote 3 · Manga)" in r
    assert "Si ya terminaste en El Retiro, decí _terminamos_ y te paso el resumen." in r
    _mandar(db, "vacuné 30 vaquillonas")
    assert _ultimo(db).nombre_establecimiento == "El Retiro"
    assert "SESIÓN CERRADA\n📍 El Retiro" in _mandar(db, "terminamos").replace("*", "")


def test_estoy_en_un_campo_con_una_sesion_sin_establecimiento(db, ia, reloj):
    respuestas, _ = ia
    con_perfil(db, TEL)
    respuestas["empiezo siembra"] = {"intencion": "abrir_sesion", "sesion": {"actividad": "siembra"}}
    _mandar(db, "empiezo siembra")
    r = _mandar(db, "estoy en el ombú")
    assert "Si ya terminaste, decí _terminamos_ y te paso el resumen." in r


def test_terminamos_cierra_con_el_resumen(db, ia, reloj):
    con_perfil(db, TEL)
    _mandar(db, "arranco manga en el retiro lote 3")
    reloj.pasar(hours=1)
    _mandar(db, "vacuné 30 vaquillonas")
    _mandar(db, "desparasité 20 terneros")
    reloj.pasar(hours=3, minutes=25)

    r = _mandar(db, "terminamos")
    assert r.startswith("⏹️ *SESIÓN CERRADA*\n📍 El Retiro · Lote 3 · Manga\n")
    assert "🕐 Jue 15/10/2026 08:00 a 12:25 (4 h 25 min)" in r
    assert "📋 2 registros" in r
    assert "Vacunación: *30* animales" in r and "Desparasitación: *20* animales" in r
    sesion = db.scalar(select(Sesion))
    assert sesion.motivo_cierre == sesiones.PEDIDO and _abiertas(db) == []

    assert _mandar(db, "terminamos") == sesiones.SIN_SESION


def test_cerrar_sesion_es_un_comando_fijo(db, ia, reloj):
    _, llamadas = ia
    con_perfil(db, TEL)
    _mandar(db, "arranco manga en el retiro lote 3")
    llamadas.clear()
    r = _mandar(db, "Cerrar sesión")
    assert "SESIÓN CERRADA" in r and "_No anotaste nada en esta sesión._" in r
    assert llamadas == []


def test_anotar_y_terminar_en_el_mismo_mensaje(db, ia, reloj):
    respuestas, _ = ia
    con_perfil(db, TEL)
    _mandar(db, "arranco manga en el retiro lote 3")
    respuestas["vacuné 30 vaquillonas y terminamos"] = {
        "acciones": [respuestas["vacuné 30 vaquillonas"], {"intencion": "cerrar_sesion"}]
    }
    r = _mandar(db, "vacuné 30 vaquillonas y terminamos")
    assert r.index("ANOTADO") < r.index("SESIÓN CERRADA")
    assert "📋 1 registro" in r and _ultimo(db).sesion_id is not None


def test_abrir_otra_cierra_la_anterior_con_su_resumen(db, ia, reloj):
    respuestas, _ = ia
    con_perfil(db, TEL)
    respuestas["empiezo siembra lote los pinos"] = {
        "intencion": "abrir_sesion",
        "sesion": {"lote": "Los Pinos", "actividad": "siembra"},
    }
    _mandar(db, "arranco manga en el retiro lote 3")
    _mandar(db, "vacuné 30 vaquillonas")
    r = _mandar(db, "empiezo siembra lote los pinos")

    assert r.index("SESIÓN CERRADA") < r.index("SESIÓN ABIERTA")
    assert "📋 1 registro" in r
    # Sin campo, la sesión nueva es en el campo actual.
    assert "📍 El Retiro · Lote los pinos · Siembra" in r
    cerradas = db.scalars(select(Sesion).where(Sesion.cerrada.is_not(None))).all()
    assert [s.motivo_cierre for s in cerradas] == [sesiones.OTRA] and len(_abiertas(db)) == 1


def test_sin_campo_actual_la_sesion_queda_sin_establecimiento(db, ia, reloj):
    respuestas, _ = ia
    con_perfil(db, TEL)
    respuestas["empiezo siembra"] = {"intencion": "abrir_sesion", "sesion": {"actividad": "siembra"}}
    assert "📍 _sin establecimiento_ · Siembra" in _mandar(db, "empiezo siembra")


def test_se_cierra_sola_a_las_12_horas_sin_mensajes(db, ia, reloj):
    con_perfil(db, TEL)
    _mandar(db, "arranco manga en el retiro lote 3")
    _mandar(db, "vacuné 30 vaquillonas")
    reloj.pasar(hours=11)
    _mandar(db, "ayuda")  # cualquier mensaje cuenta como actividad, aunque no pase por la IA
    reloj.pasar(hours=11)
    _mandar(db, "desparasité 20 terneros")
    assert _ultimo(db).sesion_id is not None  # 22 horas después de abrir, pero con actividad

    reloj.pasar(hours=12, minutes=1)
    r = _mandar(db, "vacuné 30 vaquillonas")
    assert r.startswith("⏱️ Pasaron 12 horas sin mensajes y la sesión se cerró sola.\n\n⏹️ *SESIÓN CERRADA*")
    assert "📋 2 registros" in r and "ANOTADO" in r
    assert _ultimo(db).sesion_id is None  # el mensaje que llega después ya no entra en la sesión
    sesion = db.scalar(select(Sesion))
    assert sesion.motivo_cierre == sesiones.TIEMPO
    cerrada = sesion.cerrada if sesion.cerrada.tzinfo else sesion.cerrada.replace(tzinfo=UTC)
    assert cerrada == INICIO + timedelta(hours=22 + 12)  # 12 horas después del último mensaje


def test_cada_persona_tiene_su_sesion(db, ia, reloj):
    con_perfil(db, TEL)
    con_perfil(db, OTRO)
    _mandar(db, "arranco manga en el retiro lote 3")
    _mandar(db, "vacuné 30 vaquillonas", telefono=OTRO)
    assert _ultimo(db).sesion_id is None
    assert _mandar(db, "terminamos", telefono=OTRO) == sesiones.SIN_SESION
    assert len(_abiertas(db)) == 1
