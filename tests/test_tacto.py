"""Tacto vaca por vaca y cierre del lote (etapa 2, paso 3). La IA falsa devuelve lo que tiene
que devolver la de verdad; las cuentas y las respuestas las hace el código."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.ia import interprete
from app.infra.config import config
from app.infra.modelos import Evento, Sesion, UsoDiario
from app.nucleo import pipeline
from tests.ayudas import con_perfil

HOY = date(2026, 10, 23)
AHORA = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
TEL = "5491100000001"


def _vacas(*vacas: tuple) -> dict:
    return {
        "intencion": "tacto",
        "tacto": {"vacas": [{"caravana": c, "resultado": r, "estadio": e, "cc": cc} for c, r, e, cc in vacas]},
    }


def _cierre(
    establecimiento: str | None = None, categoria: str | None = None, lote: str | None = None, **numeros
) -> dict:
    return {
        "intencion": "tacto",
        "establecimiento": establecimiento,
        "tacto": {"vacas": [], "cierre": numeros, "categoria_animal": categoria, "lote": lote},
    }


SAN_PEDRO = _cierre("San Pedro", "vaquillonas", prenadas=88, cabeza=60, cuerpo=20, cola=8, vacias=14, cc=3.2)
DICHAS: dict[str, object] = {
    "arranco tacto en la pastora": {
        "intencion": "abrir_sesion",
        "establecimiento": "La Pastora",
        "sesion": {"lote": None, "actividad": "tacto"},
    },
    "213 preñada cabeza cc 3, 214 vacía, 215 cola": _vacas(
        ("213", "prenada", "cabeza", 3), ("214", "vacia", None, 2.5), ("215", None, "cola", None)
    ),
    "216 preñada cuerpo": _vacas(("216", "Preñada", "cuerpo", 4)),
    "la 214 no, estaba preñada cabeza": _vacas(("214", "prenada", "cabeza", None)),
    "terminamos": {"intencion": "cerrar_sesion"},
    "terminamos lote vaquillonas san pedro": {"acciones": [SAN_PEDRO, {"intencion": "cerrar_sesion"}]},
    "cierre: 3 preñadas, 1 vacía": _cierre(prenadas=3, vacias=1),
    "88 preñadas 60 cabeza 20 cuerpo 6 cola 14 vacías": _cierre(prenadas=88, cabeza=60, cuerpo=20, cola=6, vacias=14),
    "lote vaquillonas": _cierre("San Pedro", None, "vaquillonas", prenadas=10, vacias=2),
    "la 300 ehh no sé": _vacas(("300", None, None, 9), ("301", "vacia", None, None)),
}


@pytest.fixture
def ia(monkeypatch):
    monkeypatch.setattr(pipeline, "_ahora", lambda: AHORA)
    monkeypatch.setattr(interprete, "interpretar", lambda texto, *_a, **_k: DICHAS[texto.lower()])


def _mandar(db, texto: str) -> str:
    return pipeline.manejar_mensaje(db, TEL, texto, hoy=HOY)


def test_el_ejemplo_de_la_especificacion_sin_sesion(db, ia):
    """Sin sesión abierta, el "terminamos" no responde "no tenés ninguna sesión abierta"."""
    con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, "terminamos lote vaquillonas san pedro")
    assert r.startswith("🩺 *CIERRE DE TACTO*\n📍 San Pedro · Vaquillonas\n\n")
    for linea in ("Preñadas: *88* (86,3 %)", "› Cabeza 60 · Cuerpo 20 · Cola 8", "Vacías: *14*"):
        assert linea in r
    assert "Total: *102* vientres" in r and "CC promedio: *3,2*" in r
    assert "sesión" not in r and "⚠️" not in r
    cierre = db.scalars(select(Evento)).one()
    assert (cierre.categoria, cierre.tipo, cierre.cantidad_animales, cierre.categoria_animal) == (
        "reproduccion",
        "tacto",
        102,
        "vaquillonas",
    )
    assert cierre.lote is None and cierre.establecimiento.nombre == "San Pedro"
    # Se guarda lo que dijo; las cuentas se hacen al mostrar.
    assert cierre.extra == {
        "tacto": {
            "es": "cierre",
            "prenadas": 88,
            "cabeza": 60,
            "cuerpo": 20,
            "cola": 8,
            "vacias": 14,
            "total": None,
            "cc": 3.2,
        }
    }


def test_vaca_por_vaca_en_una_sesion_y_el_cierre_de_la_sesion_hace_las_cuentas(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, "arranco tacto en la pastora")
    r = _mandar(db, "213 preñada cabeza cc 3, 214 vacía, 215 cola")
    assert r.startswith("🩺 *TACTO ANOTADO* · 3 vacas\n📍 La Pastora · ▶️ en la sesión\n\n")
    assert "› 213 · Preñada cabeza · CC 3\n" in r and "› 214 · Vacía · CC 2,5\n" in r and "› 215 · Preñada cola" in r
    assert "📊 *En la sesión* · 3 vacas" in r and "Preñadas: *2* (66,7 %)" in r

    r = _mandar(db, "216 preñada cuerpo")
    assert "📊 *En la sesión* · 4 vacas" in r and "Preñadas: *3* (75 %)" in r
    assert "CC promedio: *3,2* (de 3 con CC)" in r  # (3 + 2,5 + 4) / 3

    r = _mandar(db, "terminamos")
    assert r.startswith("⏹️ *SESIÓN CERRADA*")
    assert "🩺 *Tacto vaca por vaca* · 4 vacas\n" in r and "Preñadas: *3* (75 %)" in r and "Vacías: *1*" in r
    assert "Caravana 213 · Preñada cabeza · CC 3" in r  # las tarjetas muestran el resultado
    vacas = db.scalars(select(Evento).order_by(Evento.id)).all()
    assert [v.caravana for v in vacas] == ["213", "214", "215", "216"]
    assert all(v.cantidad_animales is None and v.sesion_id for v in vacas)


def test_la_misma_caravana_otra_vez_en_la_sesion_reemplaza_a_la_anterior(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, "arranco tacto en la pastora")
    _mandar(db, "213 preñada cabeza cc 3, 214 vacía, 215 cola")
    r = _mandar(db, "la 214 no, estaba preñada cabeza")
    assert "› 214 · Preñada cabeza _(antes: vacía)_" in r
    assert "📊 *En la sesión* · 3 vacas" in r and "Preñadas: *3* (100 %)" in r
    assert [v.caravana for v in db.scalars(select(Evento).order_by(Evento.id))] == ["213", "215", "214"]


def test_el_cierre_se_compara_con_las_vacas_dictadas_desde_el_cierre_anterior(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, "arranco tacto en la pastora")
    _mandar(db, "213 preñada cabeza cc 3, 214 vacía, 215 cola")
    r = _mandar(db, "cierre: 3 preñadas, 1 vacía")
    assert "⚠️ Las vacas que dictaste en la sesión (3 vacas) no dan lo mismo que el cierre:" in r
    assert "› Preñadas: 2 dictadas, 3 en el cierre" in r and "› Total: 3 dictadas, 4 en el cierre" in r
    # Después del cierre, se cuenta de cero; el resumen ya no suma esas vacas.
    r = _mandar(db, "216 preñada cuerpo")
    assert "📊 *Desde el último cierre* · 1 vaca\n" in r
    r = _mandar(db, "terminamos")
    assert "🩺 *Tacto vaca por vaca* · 1 vaca sin cierre" in r
    assert "Tacto: *4* animales" in r  # el total del cierre, en los totales de la sesión


def test_terminamos_con_el_cierre_cierra_la_sesion(db, ia):
    con_perfil(db, TEL, rubro="productor")
    _mandar(db, "arranco tacto en la pastora")
    r = _mandar(db, "terminamos lote vaquillonas san pedro")
    cierre, sesion = r.split(pipeline.SEPARADOR)
    assert cierre.startswith("🩺 *CIERRE DE TACTO*\n📍 San Pedro · Vaquillonas\n")
    assert "Quedó en *San Pedro*, fuera de la sesión abierta" in cierre  # la sesión era en La Pastora
    assert sesion.startswith("⏹️ *SESIÓN CERRADA*")
    assert db.scalars(select(Sesion)).one().cerrada is not None


def test_si_cabeza_cuerpo_y_cola_no_dan_se_guarda_como_lo_dijo_y_se_avisa(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, "88 preñadas 60 cabeza 20 cuerpo 6 cola 14 vacías")
    assert "Preñadas: *88* (86,3 %)" in r and "⚠️ Cabeza, cuerpo y cola suman 86; dijiste 88." in r


def test_lote_vaquillonas_es_la_categoria(db, ia):
    """Aunque la IA ponga "vaquillonas" en el lote, el código lo pasa a la categoría."""
    con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, "lote vaquillonas")
    cierre = db.scalars(select(Evento)).one()
    assert (cierre.lote, cierre.categoria_animal) == (None, "vaquillonas")


def test_una_vaca_sin_resultado_no_se_anota_y_se_avisa(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, "la 300 ehh no sé")
    assert "🩺 *TACTO ANOTADO* · 1 vaca" in r and "› 301 · Vacía" in r
    assert "🤔 Una vaca no la entendí: decime si está preñada (cabeza, cuerpo o cola) o vacía." in r
    assert "Con una sesión abierta" in r
    assert [e.caravana for e in db.scalars(select(Evento))] == ["301"]


def test_el_agronomo_no_tiene_tacto(db, ia):
    con_perfil(db, TEL, rubro="agronomo")
    assert _mandar(db, "216 preñada cuerpo") == pipeline.FUERA_DE_ALCANCE


def test_borrar_deshace_las_vacas_del_ultimo_mensaje(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, "arranco tacto en la pastora")
    _mandar(db, "213 preñada cabeza cc 3, 214 vacía, 215 cola")
    _mandar(db, "216 preñada cuerpo")
    assert _mandar(db, "borrar").startswith("🗑️ *BORRADO*")
    assert [e.caravana for e in db.scalars(select(Evento).order_by(Evento.id))] == ["213", "214", "215"]


@pytest.mark.parametrize(("con_sesion", "limite"), [(False, 80), (True, 300)])
def test_con_una_sesion_abierta_el_limite_diario_sube_a_300(db, ia, monkeypatch, con_sesion, limite):
    assert (config.limite_diario_ia, config.limite_diario_ia_sesion) == (80, 300)
    usuario = con_perfil(db, TEL, rubro="veterinario")
    if con_sesion:
        _mandar(db, "arranco tacto en la pastora")
    uso = db.scalars(select(UsoDiario).where(UsoDiario.usuario_id == usuario.id)).one_or_none()
    if uso is None:
        uso = UsoDiario(usuario_id=usuario.id, fecha=HOY, cantidad=0)
        db.add(uso)
    uso.cantidad = limite - 1
    db.flush()
    assert _mandar(db, "216 preñada cuerpo").startswith("🩺 *TACTO ANOTADO*")
    assert _mandar(db, "216 preñada cuerpo") == pipeline.SIN_CUPO


def test_la_sesion_cerrada_por_tiempo_vuelve_al_limite_de_80(db, ia, monkeypatch):
    usuario = con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, "arranco tacto en la pastora")
    db.scalars(select(UsoDiario).where(UsoDiario.usuario_id == usuario.id)).one().cantidad = 100
    monkeypatch.setattr(pipeline, "_ahora", lambda: AHORA + timedelta(hours=13))
    assert _mandar(db, "216 preñada cuerpo").endswith(pipeline.SIN_CUPO)
