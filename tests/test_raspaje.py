"""Raspaje de toros (etapa 2, paso 4). La IA falsa devuelve lo que tiene que devolver la de
verdad; el muestreo, las fechas y las respuestas las hace el código."""

import io
from datetime import UTC, date, datetime
from typing import Any

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.ia import interprete
from app.infra.modelos import Animal, Establecimiento, Evento, Pendiente
from app.nucleo import pipeline
from app.nucleo.cuaderno import Cuaderno
from tests.ayudas import con_perfil

HOY = date(2026, 10, 13)
AHORA = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)
TEL = "5491100000001"


def _toro(caravana=None, resultado=None, rp=None, enfermedad=None, muestreo=None, repetir_en=None) -> dict:
    return {
        "caravana": caravana,
        "rp": rp,
        "resultado": resultado,
        "enfermedad": enfermedad,
        "muestreo": muestreo,
        "repetir_en": repetir_en,
    }


def _raspaje(*toros: dict, establecimiento=None, laboratorio=False) -> dict:
    return {
        "intencion": "raspaje",
        "establecimiento": establecimiento,
        "raspaje": {"toros": list(toros), "laboratorio": laboratorio},
    }


ESPECIFICACION = "toro caravana 405 raspaje negativo, el 412 presentó muestra dudosa, repetir en 15 días"
DICHAS: dict[str, object] = {
    ESPECIFICACION: _raspaje(
        _toro("405", "negativo"), _toro("412", "dudoso", repetir_en="15 días"), establecimiento="La Pastora"
    ),
    "raspamos el 412 de nuevo, negativo": _raspaje(_toro("412", "negativo")),
    "el 412 no, era negativo": _raspaje(_toro("412", "negativo")),
    "segundo raspaje del 405, negativo": _raspaje(_toro("405", "negativo", muestreo=2)),
    "raspamos el 405 y el 412, mandé las muestras": _raspaje(_toro("405"), _toro("412")),
    "llegó el del 405: negativo": _raspaje(_toro("405", "negativo"), laboratorio=True),
    "llegó el del 412: dudoso, repetir en 2 semanas": _raspaje(
        _toro("412", "dudoso", repetir_en="2 semanas"), laboratorio=True
    ),
    "llegó el del 999: negativo": _raspaje(_toro("999", "negativo"), laboratorio=True),
    "rp 412 negativo a trico y positivo a campylo": _raspaje(
        _toro(rp="RP 412", resultado="negativo", enfermedad="trico"),
        _toro(rp="412", resultado="positivo", enfermedad="Campylobacter"),
    ),
    "¿cómo dio el 412?": {"intencion": "consultar", "consulta": {"caravana": "412"}},
    "¿cómo dio el 405?": {"intencion": "consultar", "consulta": {"caravana": "405"}},
    "el 405 negativo, repetir pronto": _raspaje(_toro("405", "negativo", repetir_en="pronto")),
    "uno sin número, negativo": _raspaje(_toro(None, "negativo"), _toro("405", "negativo")),
    "mandame el pdf de los raspajes": {
        "intencion": "exportar",
        "exportar": {"formato": "pdf"},
        "consulta": {"tipo": "raspaje"},
    },
    "arranco manga en la pastora": {
        "intencion": "abrir_sesion",
        "establecimiento": "La Pastora",
        "sesion": {"lote": None, "actividad": "manga"},
    },
    "terminamos": {"intencion": "cerrar_sesion"},
    "raspamos los toros en la pastora": {
        "intencion": "raspaje",
        "establecimiento": "La Pastora",
        "raspaje": {"toros": [], "laboratorio": False, "lote": None, "fecha_evento": {"dias": -1}},
    },
}


@pytest.fixture
def ia(monkeypatch):
    monkeypatch.setattr(pipeline, "_ahora", lambda: AHORA)
    monkeypatch.setattr(interprete, "interpretar", lambda texto, *_a, **_k: DICHAS[texto.lower()])


def _mandar(db, texto: str, hoy: date = HOY) -> str:
    return pipeline.manejar_mensaje(db, TEL, texto, hoy=hoy)


def _extra(e: Evento) -> dict[str, Any]:
    assert e.extra is not None
    return e.extra


def _raspajes(db) -> list[Evento]:
    return list(db.scalars(select(Evento).where(Evento.tipo == "raspaje").order_by(Evento.id)))


def test_el_ejemplo_de_la_especificacion(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, ESPECIFICACION)
    assert r.startswith("🔬 *RASPAJE ANOTADO* · 2 toros\n📍 La Pastora\n\n")
    assert "› Toro 405 · 1.° raspaje · Negativo\n" in r
    assert "› Toro 412 · 1.° raspaje · Dudoso · repetir el 28/10" in r
    assert "📌 *PENDIENTE ANOTADO*\n      Repetir raspaje: toro 412 · 📅 Para el Mié 28/10/2026" in r
    assert "apto" not in r.lower() and "⚠️" not in r

    toros = db.scalars(select(Animal).order_by(Animal.id)).all()
    assert [(t.caravana, t.rp, t.categoria, t.establecimiento.nombre) for t in toros] == [
        ("405", None, "toro", "La Pastora"),
        ("412", None, "toro", "La Pastora"),
    ]
    r405, r412 = _raspajes(db)
    assert (r405.categoria, r405.categoria_animal, r405.caravana, r405.animal_id) == (
        "sanidad",
        "toro",
        "405",
        toros[0].id,
    )
    pendiente = db.scalars(select(Pendiente)).one()
    assert pendiente.vence == date(2026, 10, 28) and pendiente.establecimiento.nombre == "La Pastora"
    assert r412.extra == {
        "raspaje": {"es": "raspaje", "resultados": {"": "dudoso"}, "muestreo": 1, "repetir": "2026-10-28"},
        "pendientes": [pendiente.id],
    }
    assert _extra(r405)["raspaje"]["repetir"] is None and "pendientes" not in _extra(r405)


def test_el_muestreo_sigue_la_serie_hasta_60_dias(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, ESPECIFICACION)
    assert "› Toro 412 · 2.° raspaje · Negativo" in _mandar(
        db, "raspamos el 412 de nuevo, negativo", date(2026, 10, 28)
    )
    # 3.° a los 60 días del 2.°; al año siguiente, de nuevo el 1.°.
    assert "› Toro 412 · 3.° raspaje" in _mandar(db, "raspamos el 412 de nuevo, negativo", date(2026, 12, 27))
    assert "› Toro 412 · 1.° raspaje" in _mandar(db, "raspamos el 412 de nuevo, negativo", date(2027, 10, 1))
    assert len(db.scalars(select(Animal)).all()) == 2  # el mismo toro de siempre


def test_el_numero_que_dice_queda_y_se_avisa_si_no_coincide(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, "segundo raspaje del 405, negativo")
    assert "› Toro 405 · 2.° raspaje · Negativo" in r
    assert "⚠️ Toro 405: dijiste 2.° raspaje; en lo anotado sería el 1.°. Quedó el 2.°." in r
    # El siguiente sigue desde el que dijo.
    assert "› Toro 405 · 3.° raspaje" in _mandar(db, "raspamos el 405 y el 412, mandé las muestras", date(2026, 10, 20))


def test_el_mismo_toro_el_mismo_dia_reemplaza_al_anterior(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, ESPECIFICACION)
    r = _mandar(db, "el 412 no, era negativo")
    assert "› Toro 412 · 1.° raspaje · Negativo _(antes: dudoso)_" in r
    assert [e.caravana for e in _raspajes(db)] == ["405", "412"]
    assert db.scalars(select(Pendiente)).all() == []  # la repetición del dudoso se fue con él


def test_el_resultado_del_laboratorio_y_borrarlo(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, "raspamos el 405 y el 412, mandé las muestras")
    assert "› Toro 405 · 1.° raspaje · Esperando resultado" in r

    r = _mandar(db, "llegó el del 405: negativo", date(2026, 10, 16))
    assert r.startswith("🧪 *RESULTADO DE LABORATORIO* · 1 toro\n\n")
    assert "› Toro 405 · 1.° raspaje del 13/10 · Negativo _(antes: esperando resultado)_" in r
    raspado, _, lab = _raspajes(db)
    assert lab.fecha_evento == date(2026, 10, 16) and lab.animal_id == raspado.animal_id
    assert _extra(lab)["raspaje"] == {"es": "laboratorio", "de": raspado.id, "resultados": {"": "negativo"}}
    assert _extra(raspado)["raspaje"]["laboratorio"]["resultados"] == {"": "negativo"}

    # Las consultas muestran el resultado que llegó.
    r = _mandar(db, "¿cómo dio el 405?")
    assert "Caravana 405 · 1.° raspaje · Negativo (laboratorio)" in r
    assert "Caravana 405 · Resultado de laboratorio · Negativo" in r
    assert "Caravana 412 · 1.° raspaje · Esperando resultado" in _mandar(db, "¿cómo dio el 412?")

    # "borrar" deshace el resultado: el raspaje vuelve a esperar.
    assert _mandar(db, "borrar").startswith("🗑️ *BORRADO*")
    assert [e.id for e in _raspajes(db)] == [raspado.id, raspado.id + 1]
    db.refresh(raspado)
    assert "laboratorio" not in _extra(raspado)["raspaje"]
    assert "Caravana 405 · 1.° raspaje · Esperando resultado" in _mandar(db, "¿cómo dio el 405?")


def test_el_laboratorio_con_repeticion_cuenta_desde_hoy(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, ESPECIFICACION)
    r = _mandar(db, "llegó el del 412: dudoso, repetir en 2 semanas", date(2026, 10, 20))
    assert "Dudoso _(antes: dudoso)_ · repetir el 03/11" in r
    assert {p.vence for p in db.scalars(select(Pendiente))} == {date(2026, 10, 28), date(2026, 11, 3)}
    assert _mandar(db, "borrar", date(2026, 10, 20)).startswith("🗑️ *BORRADO*")
    assert {p.vence for p in db.scalars(select(Pendiente))} == {date(2026, 10, 28)}


def test_el_laboratorio_sin_raspaje_anotado_no_guarda_nada(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, "llegó el del 999: negativo")
    assert r.startswith("🔍 No encontré un raspaje anotado del toro 999.")
    assert _raspajes(db) == []


def test_el_laboratorio_con_el_mismo_toro_en_dos_campos_pregunta(db, ia):
    usuario = con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, ESPECIFICACION)
    cuaderno = Cuaderno(db, usuario)
    retiro = cuaderno.establecimiento("El Retiro")
    toro = cuaderno.animal(None, "405", retiro, "toro")
    assert toro is not None
    db.add(
        Evento(
            cuenta_id=usuario.cuenta_id,
            usuario_id=usuario.id,
            categoria="sanidad",
            tipo="raspaje",
            establecimiento=retiro,
            animal_id=toro.id,
            fecha_evento=HOY,
            extra={"raspaje": {"es": "raspaje", "resultados": {}, "muestreo": 1}},
        )
    )
    usuario.establecimiento_actual = None
    db.flush()
    r = _mandar(db, "llegó el del 405: negativo")
    assert "🤔 Hay un toro 405 en La Pastora y El Retiro: decime de qué campo es el resultado." in r


def test_rp_y_resultados_por_enfermedad(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, "rp 412 negativo a trico y positivo a campylo")
    assert "› Toro RP 412 · 1.° raspaje · Campylobacter: positivo · Tricomoniasis: negativo" in r
    toro = db.scalars(select(Animal)).one()
    assert (toro.rp, toro.caravana) == ("412", None)
    (raspado,) = _raspajes(db)
    assert raspado.caravana is None
    # "el 412", dicho como caravana, encuentra al RP 412.
    r = _mandar(db, "¿cómo dio el 412?")
    assert "toro · RP 412 · 1.° raspaje · Campylobacter: positivo · Tricomoniasis: negativo" in r


def test_lo_que_no_entiende_lo_avisa(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, "el 405 negativo, repetir pronto")
    assert "🤔 No entendí cuándo repetir el raspaje del toro 405 (_pronto_): decime en cuántos días." in r
    assert db.scalars(select(Pendiente)).all() == []
    r = _mandar(db, "uno sin número, negativo", date(2026, 10, 14))
    assert "🤔 Un toro no lo entendí: decime su caravana o su RP." in r


def test_borrar_deshace_el_raspaje_y_su_pendiente(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, ESPECIFICACION)
    assert _mandar(db, "borrar").startswith("🗑️ *BORRADO*")
    assert _raspajes(db) == [] and db.scalars(select(Pendiente)).all() == []


def test_el_resumen_de_la_sesion_cuenta_los_toros_por_resultado(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, "arranco manga en la pastora")
    r = _mandar(db, "raspamos el 405 y el 412, mandé las muestras")
    assert "📍 La Pastora · ▶️ en la sesión" in r
    _mandar(db, "llegó el del 405: negativo")
    r = _mandar(db, "terminamos")
    assert "🔬 *Raspaje* · 2 toros\n      Negativo 1 · Esperando resultado 1" in r


def test_el_pdf_registro_de_raspajes(db, ia):
    con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, ESPECIFICACION)
    respuesta = pipeline.atender(db, TEL, "mandame el pdf de los raspajes", hoy=HOY)
    assert respuesta.texto.startswith("📄 *PDF LISTO*")
    (adjunto,) = respuesta.adjuntos
    assert adjunto.nombre == "Anotagro-raspajes-2026-10-13.pdf"
    texto = " ".join(" ".join(p.extract_text() for p in PdfReader(io.BytesIO(adjunto.contenido)).pages).split())
    assert "Registro de raspajes" in texto and "Resultados" in texto and "Toros raspados: 2" in texto
    assert "Negativo: 1" in texto and "Dudoso: 1" in texto and "28/10/2026" in texto
    assert "no es un certificado" in texto and "apto" not in texto.lower()


def test_un_raspaje_sin_ningun_toro_se_anota_como_registrar(db, ia):
    """ "Raspamos 12 toros en La Pastora" es "registrar"; si la IA lo manda como "raspaje" sin
    toros, queda el mismo registro, sin animales."""
    con_perfil(db, TEL, rubro="veterinario")
    r = _mandar(db, "raspamos los toros en la pastora")
    (e,) = _raspajes(db)
    assert (e.categoria, e.tipo, e.categoria_animal, e.animal_id, e.extra) == (
        "sanidad",
        "raspaje",
        "toros",
        None,
        None,
    )
    assert e.nombre_establecimiento == "La Pastora" and e.fecha_evento == date(2026, 10, 12)
    assert "Raspaje" in r and "📍 La Pastora" in r
    assert db.scalars(select(Animal)).all() == []


def test_el_agronomo_no_tiene_raspaje(db, ia):
    con_perfil(db, TEL, rubro="agronomo")
    assert _mandar(db, ESPECIFICACION) == pipeline.FUERA_DE_ALCANCE


def test_unir_y_borrar_campos_con_toros(db, ia):
    usuario = con_perfil(db, TEL, rubro="veterinario")
    _mandar(db, ESPECIFICACION)
    cuaderno = Cuaderno(db, usuario)
    retiro = cuaderno.establecimiento("El Retiro")
    assert retiro is not None
    otro_405 = cuaderno.animal(None, "405", retiro, "toro")
    solo_retiro = cuaderno.animal("900", None, retiro, "toro")
    pastora = db.scalars(select(Establecimiento).where(Establecimiento.nombre == "La Pastora")).one()
    assert otro_405 is not None and solo_retiro is not None

    cuaderno.unir_establecimientos(retiro.id, pastora.id)
    toros = db.scalars(select(Animal).order_by(Animal.id)).all()
    assert [(t.caravana, t.rp) for t in toros] == [("405", None), ("412", None), (None, "900")]
    assert otro_405.id not in {t.id for t in toros} and solo_retiro.establecimiento_id == pastora.id

    cuaderno.borrar_establecimiento(pastora.id)
    assert db.scalars(select(Animal)).all() == []
