"""Renombrar y unir campos y lotes (paso 8.7 del plan)."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.ia import interprete
from app.infra.modelos import Auditoria, Establecimiento, Evento, Lote, Pendiente, Sesion, Usuario
from app.nucleo import pipeline, respuestas
from app.nucleo.cuaderno import Cuaderno
from tests.ayudas import con_perfil

HOY = date(2026, 10, 15)
TEL = "5491100000001"
AHORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
LLUVIA = {"categoria": "campo", "tipo": "lluvia", "valor": 20, "unidad": "mm"}


def _renombrar(campo: str | None, nuevo: str, lote: str | None = None) -> dict:
    return {"intencion": "renombrar_campo", "renombrar": {"campo": campo, "lote": lote, "nuevo": nuevo}}


@pytest.fixture
def ia(monkeypatch):
    dichas: dict[str, object] = {
        "estoy en omu": {"intencion": "establecimiento", "establecimiento": "Omu"},
        "estoy en el ombú": {"intencion": "establecimiento", "establecimiento": "El Ombú"},
        "llovió 20 mm en el ombú": {"intencion": "registrar", "establecimiento": "El Ombú", "eventos": [LLUVIA]},
        "omu en realidad es el ombú": _renombrar("Omu", "El Ombú"),
        "este campo se llama la pastora": _renombrar(None, "La Pastora"),
        "uní omu con el ombú": _renombrar("Omu", "El Ombú"),
        "el lote 3 se llama los pinos": _renombrar(None, "Los Pinos", lote="3"),
        "uní el lote 3 con el 5": _renombrar(None, "5", lote="3"),
        "mis campos, porfa": {"intencion": "mis_campos"},
        "no, no le cambies el nombre, el ombú es otro campo": {"intencion": "cancelar"},
    }
    reloj = {"ahora": AHORA}
    monkeypatch.setattr(pipeline, "_ahora", lambda: reloj["ahora"])
    monkeypatch.setattr(interprete, "interpretar", lambda texto, *_a, **_k: dichas[texto.lower()])
    return dichas, reloj


def _mandar(db, texto):
    return pipeline.manejar_mensaje(db, TEL, texto, hoy=HOY)


def _campos(db) -> list[str]:
    return list(db.scalars(select(Establecimiento.nombre).order_by(Establecimiento.id)))


def _evento(campo: Establecimiento | None, lote: Lote | None = None, **datos) -> Evento:
    return Evento(establecimiento=campo, lote=lote, categoria="campo", tipo="lluvia", fecha_evento=HOY, **datos)


def _cargar(db) -> tuple[Usuario, Establecimiento, Establecimiento]:
    """Omu (el campo actual) con un registro en el lote 3, un pendiente y una sesión; El
    Ombú con su lote 3 y un registro."""
    usuario = con_perfil(db, TEL)
    cuaderno = Cuaderno(db, usuario)
    cuaderno.permitidos = {"omu", "el ombu"}
    omu, ombu = cuaderno.establecimiento("Omu"), cuaderno.establecimiento("El Ombú")
    assert omu is not None and ombu is not None
    lote_omu, lote_ombu = cuaderno.lote("3", omu), cuaderno.lote("3", ombu)
    cuaderno.lote("potrero grande", omu)
    cuaderno.agregar([_evento(omu, lote_omu), _evento(ombu, lote_ombu)])
    cuaderno.agregar_pendiente(Pendiente(texto="arreglar el molino", establecimiento=omu, creado=AHORA))
    cuaderno.abrir_sesion(omu, lote_omu, "manga", AHORA)
    usuario.establecimiento_actual = omu
    db.flush()
    return usuario, omu, ombu


# --- Renombrar ---------------------------------------------------------------------


def test_renombrar_un_campo_deja_lo_anotado_igual(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en omu")
    r = _mandar(db, "Omu en realidad es El Ombú")
    assert r == "✏️ *CAMPO RENOMBRADO*\n\n*Omu* ahora se llama *El Ombú*. Lo anotado ahí sigue igual."
    campo = db.scalar(select(Establecimiento))
    assert (campo.nombre, campo.clave) == ("El Ombú", "el ombu")
    assert _mandar(db, "llovió 20 mm en el ombú").startswith("✅")  # no pregunta si es Omu: ya es ese
    assert [e.nombre_establecimiento for e in db.scalars(select(Evento))] == ["El Ombú"]
    assert db.scalar(select(Auditoria.accion).order_by(Auditoria.id.desc())) == "renombrar_campo"


def test_sin_decir_cual_renombra_el_campo_actual(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en omu")
    assert "*Omu* ahora se llama *La Pastora*" in _mandar(db, "este campo se llama La Pastora")


def test_sin_campo_actual_pregunta_cual(db, ia):
    con_perfil(db, TEL)
    assert _mandar(db, "este campo se llama La Pastora").startswith("🤔 ¿A qué campo le cambio el nombre?")


def test_un_campo_que_no_existe_no_se_crea(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en el ombú")
    r = _mandar(db, "Omu en realidad es El Ombú")
    assert r == "🤔 No tenés ningún campo que se llame *Omu*.\n\nTus campos: El Ombú."
    assert _campos(db) == ["El Ombú"]


def test_renombrar_un_lote(db, ia):
    _, omu, _ = _cargar(db)
    r = _mandar(db, "el lote 3 se llama los pinos")  # el campo es el de la sesión: Omu
    assert r == "✏️ *LOTE RENOMBRADO*\n\nEl *lote 3* de *Omu* ahora se llama *los pinos*."
    nombres = db.scalars(select(Lote.nombre).where(Lote.establecimiento_id == omu.id).order_by(Lote.id))
    assert list(nombres) == ["los pinos", "potrero grande"]


def test_el_campo_del_lote_puede_venir_en_establecimiento(db, ia):
    """Lo que devolvió la IA en el eval para "el lote 3 de La Pastora se llama Los Pinos"."""
    dichas, _ = ia
    _, omu, _ = _cargar(db)  # el campo actual es Omu, pero el lote es de La Pastora
    cuaderno = Cuaderno(db, db.scalar(select(Usuario)))
    cuaderno.lote("3", cuaderno.establecimiento("La Pastora"))
    dichas["el lote 3 de la pastora se llama los pinos"] = {
        **_renombrar(None, "Los Pinos", lote="3"),
        "establecimiento": "La Pastora",
    }
    r = _mandar(db, "el lote 3 de La Pastora se llama Los Pinos")
    assert r == "✏️ *LOTE RENOMBRADO*\n\nEl *lote 3* de *La Pastora* ahora se llama *los pinos*."
    assert cuaderno.lote_existente("3", omu) is not None  # el de Omu no se tocó


def test_un_lote_que_vino_como_campo(db, ia):
    """La IA puso el potrero como campo: no hay un campo con ese nombre, pero sí un lote."""
    dichas, _ = ia
    _cargar(db)
    dichas["cambiale el nombre al potrero grande, ahora es el lote 8"] = _renombrar("potrero grande", "8")
    r = _mandar(db, "cambiale el nombre al potrero grande, ahora es el lote 8")
    assert r == "✏️ *LOTE RENOMBRADO*\n\nEl *potrero grande* de *Omu* ahora se llama *lote 8*."


def test_un_lote_que_no_existe(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en omu")
    assert _mandar(db, "el lote 3 se llama los pinos").startswith("🤔 No encontré el *lote 3* en *Omu*.")


# --- Unir campos -------------------------------------------------------------------


def test_unir_campos_pregunta_y_muestra_lo_que_pasa(db, ia):
    _cargar(db)
    r = _mandar(db, "uní Omu con El Ombú")
    assert r.startswith("🔗 *¿Uno Omu con El Ombú?*\n\nYa tenés el campo *El Ombú*. Queda ese, con lo de *Omu*:")
    for linea in ("› 1 registro", "› 1 pendiente", "› 2 lotes", "› 1 sesión de trabajo"):
        assert linea in r
    assert "se juntan: lote 3." in r and "Respondé *sí* para unirlos o *no* para cancelar." in r
    assert _campos(db) == ["Omu", "El Ombú"]  # hasta el sí no cambia nada


def test_con_el_si_pasa_todo_al_que_queda(db, ia):
    usuario, omu, ombu = _cargar(db)
    omu_id, ombu_id = omu.id, ombu.id
    _mandar(db, "uní Omu con El Ombú")
    r = _mandar(db, "sí, dale")
    assert r.startswith("🔗 *CAMPOS UNIDOS*\n\nListo: lo de *Omu* pasó a *El Ombú*.")
    assert _campos(db) == ["El Ombú"]
    assert {e.establecimiento_id for e in db.scalars(select(Evento))} == {ombu_id}
    assert db.scalar(select(Pendiente.establecimiento_id)) == ombu_id
    assert db.scalar(select(Sesion.establecimiento_id)) == ombu_id
    # El lote 3 de los dos queda uno solo, con los dos registros; el potrero grande se muda.
    lotes = list(db.scalars(select(Lote).order_by(Lote.id)))
    assert [(lote.nombre, lote.establecimiento_id) for lote in lotes] == [("3", ombu_id), ("potrero grande", ombu_id)]
    assert {e.lote_id for e in db.scalars(select(Evento))} == {lotes[0].id}
    assert db.scalar(select(Sesion.lote_id)) == lotes[0].id
    assert db.get(Usuario, usuario.id).establecimiento_actual_id == ombu_id  # Omu era el actual
    fila = db.scalar(select(Auditoria).where(Auditoria.accion == "unir_campos"))
    assert fila.detalle == {"cuenta": usuario.cuenta_id, "origen": omu_id, "destino": ombu_id, "registros": 1}


@pytest.mark.parametrize("texto", ["no", "no, dejá", "cancelá", "mejor no"])
def test_cancelar_la_union_no_cambia_nada(db, ia, texto):
    _cargar(db)
    _mandar(db, "uní Omu con El Ombú")
    assert _mandar(db, texto) == "👌 Listo, no cambié nada."
    assert _campos(db) == ["Omu", "El Ombú"] and len(db.scalars(select(Lote)).all()) == 3


def test_si_pasa_mucho_tiempo_no_une(db, ia):
    _, reloj = ia
    _cargar(db)
    _mandar(db, "uní Omu con El Ombú")
    reloj["ahora"] = AHORA + timedelta(minutes=11)
    assert _mandar(db, "sí").startswith("⏱️ Pasó mucho tiempo")
    assert _campos(db) == ["Omu", "El Ombú"]


# --- Unir lotes --------------------------------------------------------------------


def test_unir_lotes_pasa_registros_traslados_pendientes_y_sesiones(db, ia):
    usuario = con_perfil(db, TEL)
    cuaderno = Cuaderno(db, usuario)
    campo = cuaderno.establecimiento("La Pastora")
    tres, cinco, otro = cuaderno.lote("3", campo), cuaderno.lote("5", campo), cuaderno.lote("7", campo)
    assert tres is not None and cinco is not None and otro is not None
    cuaderno.agregar([_evento(campo, tres), _evento(campo, otro, lote_destino=tres)])
    cuaderno.agregar_pendiente(Pendiente(texto="revisar la aguada", establecimiento=campo, lote=tres, creado=AHORA))
    cuaderno.abrir_sesion(campo, tres, "manga", AHORA)
    usuario.establecimiento_actual = campo
    db.flush()
    tres_id, cinco_id = tres.id, cinco.id

    r = _mandar(db, "uní el lote 3 con el 5")
    assert r.startswith("🔗 *¿Uno el lote 3 con el lote 5?*\n\nEn *La Pastora* ya tenés el *lote 5*.")
    assert "› 2 registros" in r and "› 1 pendiente" in r and "› 1 sesión de trabajo" in r and "lotes" not in r
    assert _mandar(db, "dale").startswith("🔗 *LOTES UNIDOS*\n\nListo: lo del *lote 3* pasó al *lote 5*.")
    assert db.get(Lote, tres_id) is None
    assert sorted((e.lote_id, e.lote_destino_id) for e in db.scalars(select(Evento))) == sorted(
        [(cinco_id, None), (otro.id, cinco_id)]
    )
    assert db.scalar(select(Pendiente.lote_id)) == cinco_id and db.scalar(select(Sesion.lote_id)) == cinco_id
    assert db.scalar(select(Auditoria.accion).order_by(Auditoria.id.desc())) == "unir_lotes"


# --- La pregunta de un campo parecido ------------------------------------------------


def test_cambiale_el_nombre_al_campo_parecido(db, ia):
    """Omu quedó mal escrito: "¿El Ombú es Omu?" -> "Sí, cambiá el nombre al Ombú"."""
    con_perfil(db, TEL)
    _mandar(db, "estoy en omu")
    pregunta = _mandar(db, "llovió 20 mm en el ombú")
    assert pregunta.startswith("🤔 *¿El Ombú es Omu?*")
    assert "*cambiale el nombre* para que Omu pase a llamarse El Ombú" in pregunta
    r = _mandar(db, "Sí, cambiá el nombre al Ombú")
    assert r.startswith("✏️ *Omu* ahora se llama *El Ombú*.\n\n✅")
    assert _campos(db) == ["El Ombú"]
    assert [e.nombre_establecimiento for e in db.scalars(select(Evento))] == ["El Ombú"]


def test_no_le_cambies_el_nombre_no_renombra(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en omu")
    _mandar(db, "llovió 20 mm en el ombú")
    # No es una respuesta fija: va a la IA, con la pregunta como contexto.
    assert _mandar(db, "No, no le cambies el nombre, El Ombú es otro campo") == "👌 Listo, no anoté nada."
    assert _campos(db) == ["Omu"] and db.scalars(select(Evento)).all() == []


@pytest.mark.parametrize(
    ("texto", "es"),
    [
        ("cambiale el nombre", True),
        ("Sí, cambiá el nombre al Ombú", True),
        ("dale, ponele el nombre nuevo", True),
        ("renombralo", True),
        ("cambiale el nombre a Omu, que se llame El Ombú", True),
        ("No, no le cambies el nombre, El Ombú es otro campo", False),
        ("no, el nombre está bien", False),
        ("sí", False),  # es el *sí* de siempre: lo anota en el que ya existe
        ("cambiale el nombre a La Pastora", False),  # otro campo: no es una respuesta clara
    ],
)
def test_que_es_cambiale_el_nombre(texto, es):
    assert respuestas.es_renombrar(texto, ["El Ombú", "Omu"]) is es


# --- Mis campos ------------------------------------------------------------------------


def test_mis_campos_muestra_los_pendientes_de_cada_campo(db, ia):
    _cargar(db)
    r = _mandar(db, "mis campos")
    assert "📍 *Omu* · 1 registro · 1 pendiente · _estás acá_" in r
    assert "📍 *El Ombú* · 1 registro\n" in r  # sin pendientes no los nombra
