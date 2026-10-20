"""Todo borrado que llega por la IA pide confirmación (paso 8.7.2 del plan).

La prueba del 20/10 contra Railway, con los campos Omu y Ombu (este el actual): la IA mandó
"borrar" donde se pedía borrar el campo, y se borraron registros sin preguntar, una vez de
un campo que no se nombró. Acá la IA falsa devuelve lo mismo que devolvió la de verdad.
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.ia import interprete
from app.infra.modelos import Establecimiento, Evento, Pendiente
from app.nucleo import pipeline
from app.nucleo.cuaderno import Cuaderno
from tests.ayudas import con_perfil

HOY = date(2026, 10, 20)
TEL = "5491100000001"
AHORA = datetime(2026, 10, 20, 17, 32, tzinfo=UTC)


def _borrar(*referencias: dict) -> dict:
    return {"intencion": "borrar", "borrado": {"registros": list(referencias)}}


def _borrar_campo(campo: str | None) -> dict:
    return {"intencion": "borrar_campo", "borrar_campo": {"campo": campo, "lote": None}}


@pytest.fixture
def ia(monkeypatch):
    dichas: dict[str, object] = {
        # Lo que devolvió la IA en Railway, según lo que respondió el bot.
        "borra el omu": _borrar({"establecimiento": "Omu"}),
        "borra el campo el omu": _borrar({"establecimiento": "Omu", "todos": True}),
        "borrar campo": _borrar_campo(None),
        "elimina el campo omu": _borrar(),
        # Y lo que tiene que devolver.
        "borrá el campo el omu": _borrar_campo("el omu"),
    }
    monkeypatch.setattr(pipeline, "_ahora", lambda: AHORA)
    monkeypatch.setattr(interprete, "interpretar", lambda texto, *_a, **_k: dichas[texto.lower()])
    return dichas


def _mandar(db, texto):
    return pipeline.manejar_mensaje(db, TEL, texto, hoy=HOY)


def _lluvia(campo: Establecimiento, mm: int, dia: int) -> Evento:
    return Evento(
        establecimiento=campo, categoria="campo", tipo="lluvia", valor=mm, unidad="mm", fecha_evento=date(2026, 10, dia)
    )


def _cargar(db) -> None:
    """Omu con 3 registros, 2 pendientes y los lotes 1 a 4; Ombu con una lluvia, el actual."""
    usuario = con_perfil(db, TEL)
    cuaderno = Cuaderno(db, usuario)
    cuaderno.permitidos = {"omu", "ombu"}
    omu, ombu = cuaderno.establecimiento("Omu"), cuaderno.establecimiento("Ombu")
    assert omu is not None and ombu is not None
    for lote in "1234":
        cuaderno.lote(lote, omu)
    cuaderno.agregar([_lluvia(omu, 12, 15), _lluvia(omu, 8, 16), _lluvia(omu, 20, 17)])
    for texto in ("revisar el molino", "arreglar el alambrado"):
        cuaderno.agregar_pendiente(Pendiente(texto=texto, establecimiento=omu))
    cuaderno.agregar([_lluvia(ombu, 5, 19)])
    usuario.establecimiento_actual = ombu
    db.flush()


def _registros(db) -> list[tuple[str | None, object]]:
    return [(e.nombre_establecimiento, e.valor) for e in db.scalars(select(Evento).order_by(Evento.id))]


def test_la_prueba_del_20_10_no_borra_nada_sin_preguntar(db, ia):
    _cargar(db)
    todo = _registros(db)

    r = _mandar(db, "Borra el omu")
    assert r.startswith("🤔 *Hay 3 registros* que coinciden con _en Omu_.\nNo borré ninguno:")

    r = _mandar(db, "Borra el campo el omu")
    assert r.startswith("⚠️ *VOY A BORRAR 3 REGISTROS*\n\n      › 🌧️ Lluvia · 20 mm · 📍 Omu")
    assert "¿Confirmás? Respondé *sí* para borrarlos o *no* para cancelar." in r

    # Otro mensaje descarta la pregunta: no se borra nada.
    r = _mandar(db, "Borrar campo")
    assert r == "🤔 *¿Qué campo querés borrar?*\n\nTus campos: Ombu, Omu.\n\nDecímelo así: _borrá el campo Ombu_."

    r = _mandar(db, "Elimina el campo omu")
    assert r.startswith("⚠️ *VOY A BORRAR 1 REGISTRO*\n\n      › 🌧️ Lluvia · 5 mm · 📍 Ombu")
    assert _mandar(db, "no") == "👌 Listo, no borré nada."
    assert _registros(db) == todo

    # Y al final se puede borrar el campo Omu.
    r = _mandar(db, "Borrá el campo el omu")
    assert r.startswith(
        "🗑️ *¿Borro el campo Omu?*\n\nSe borra con todo lo suyo:\n\n      › 3 registros\n      › 2 pendientes"
    )
    assert _mandar(db, "sí").startswith("🗑️ *CAMPO BORRADO*")
    assert _registros(db) == [("Ombu", 5)]
    assert list(db.scalars(select(Establecimiento.nombre))) == ["Ombu"]
    assert db.scalars(select(Pendiente)).all() == []


def test_deshacer_lo_ultimo_hablando_pregunta_aunque_sea_un_pendiente(db, ia):
    _cargar(db)
    ia["sacá lo último que anoté"] = _borrar()
    pipeline.manejar_mensaje(db, TEL, "borrar", hoy=HOY)  # el atajo: borra la lluvia de Ombu sin preguntar
    assert ("Ombu", 5) not in _registros(db)
    ia["anotá que tengo que llamar a juan"] = {"intencion": "anotar_pendiente", "pendiente": {"texto": "llamar a Juan"}}
    _mandar(db, "anotá que tengo que llamar a juan")
    r = _mandar(db, "sacá lo último que anoté")
    assert r.startswith("⚠️ *VOY A BORRAR 1 PENDIENTE*\n\n      › 📌 Llamar a Juan")
    assert _mandar(db, "dale") == "🗑️ *PENDIENTE BORRADO*\n\nListo, borré 1 pendiente."
    assert sorted(p.texto for p in db.scalars(select(Pendiente))) == ["arreglar el alambrado", "revisar el molino"]


def test_registros_y_pendientes_en_el_mismo_mensaje_una_sola_confirmacion(db, ia):
    _cargar(db)
    ia["borrá la lluvia de 5 y el pendiente del molino"] = {
        "acciones": [
            _borrar({"tipo": "lluvia", "establecimiento": "Ombu"}),
            {"intencion": "borrar_pendiente", "pendientes": [{"texto": "molino"}]},
        ]
    }
    r = _mandar(db, "borrá la lluvia de 5 y el pendiente del molino")
    assert "VOY A BORRAR 1 REGISTRO" in r and "VOY A BORRAR 1 PENDIENTE" in r
    assert "Respondé *sí* para borrarlos" in r  # son dos
    assert _mandar(db, "sí") == "🗑️ *BORRADO*\n\nListo, borré 1 registro y 1 pendiente."
    assert ("Ombu", 5) not in _registros(db)
    assert [p.texto for p in db.scalars(select(Pendiente))] == ["arreglar el alambrado"]
