"""Pendientes: se anotan, se consultan, se marcan hechos y se borran.

Las reglas son las de docs/arquitectura.md, decisión de producto "Pendientes".
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ia import interprete
from app.infra.modelos import Evento, Pendiente
from app.modulos.comun import pendientes
from app.nucleo import pipeline
from tests.ayudas import con_perfil

HOY = date(2026, 10, 15)  # jueves
# Las fechas como las devuelve la IA (FECHA): las calcula el código.
LUNES_PASADO = {"dia_semana": "lunes", "cual": "pasado"}
VIERNES = {"dia_semana": "viernes"}
TEL, OTRO = "5491100000001", "5491100000002"


@pytest.fixture
def ia(monkeypatch):
    """La IA falsa: cada texto tiene su respuesta. Se le suman respuestas en cada test."""
    respuestas: dict[str, dict] = {
        "estoy en la pastora": {"intencion": "establecimiento", "establecimiento": "La Pastora"},
        "arranco manga en el retiro lote 3": {
            "intencion": "abrir_sesion",
            "establecimiento": "El Retiro",
            "sesion": {"lote": "lote 3", "actividad": "manga"},
        },
        "¿qué tengo pendiente?": {"intencion": "ver_pendientes"},
        "vacuné 30 vaquillonas": {
            "intencion": "registrar",
            "eventos": [{"categoria": "sanidad", "tipo": "vacunacion", "cantidad_animales": 30}],
        },
    }
    monkeypatch.setattr(pipeline, "_ahora", lambda: datetime(2026, 10, 15, 12, 0, tzinfo=UTC))
    monkeypatch.setattr(interprete, "interpretar", lambda texto, *_a, **_k: respuestas[texto])
    return respuestas


def _anotar(ia, db, mensaje, establecimiento=None, telefono=TEL, **pendiente):
    """Manda `mensaje` y la IA falsa devuelve el pendiente con esos datos (texto, lote, vence)."""
    ia[mensaje] = {"intencion": "anotar_pendiente", "establecimiento": establecimiento, "pendiente": pendiente}
    return _mandar(db, mensaje, telefono)


def _sobre(ia, db, intencion, mensaje, *referencias, telefono=TEL):
    """Manda `mensaje` y la IA falsa devuelve "pendiente_hecho" o "borrar_pendiente" con esas referencias."""
    ia[mensaje] = {"intencion": intencion, "pendientes": list(referencias)}
    return _mandar(db, mensaje, telefono)


def _mandar(db, texto, telefono=TEL):
    return pipeline.manejar_mensaje(db, telefono, texto, hoy=HOY)


def _abiertos(db) -> list[str]:
    return list(db.scalars(select(Pendiente.texto).where(Pendiente.hecho.is_(None)).order_by(Pendiente.id)))


def _ultimo(db: Session) -> Pendiente:
    return db.scalars(select(Pendiente).order_by(Pendiente.id.desc()).limit(1)).one()


def _donde(p: Pendiente) -> tuple[str | None, str | None]:
    """El campo y el lote del pendiente, por su nombre."""
    return (p.establecimiento.nombre if p.establecimiento else None, p.lote.nombre if p.lote else None)


# --- Anotar ---------------------------------------------------------------------------


def test_anotar_un_pendiente_en_el_campo_actual(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en la pastora")
    r = _anotar(
        ia,
        db,
        "el martes reviso las aguadas del lote 3",
        texto="revisar las aguadas",
        lote="3",
        vence={"dia_semana": "martes"},
    )
    assert r.startswith("📌 *PENDIENTE ANOTADO*\n\n📌 *Revisar las aguadas*\n")
    assert "Lote 3 · 📍 La Pastora · 📅 Para el Mar 20/10/2026" in r
    p = _ultimo(db)
    assert (p.texto, _donde(p), p.vence, p.hecho) == (
        "revisar las aguadas",
        ("La Pastora", "3"),
        date(2026, 10, 20),
        None,
    )


def test_sin_campo_toma_el_de_la_sesion_sin_su_lote(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en la pastora")
    _mandar(db, "arranco manga en el retiro lote 3")
    _anotar(ia, db, "acordate de pedir vacunas", texto="pedir vacunas")
    assert _donde(_ultimo(db)) == ("El Retiro", None)


def test_nombrar_otro_campo_no_cambia_el_campo_actual(db, ia):
    u = con_perfil(db, TEL)
    _mandar(db, "estoy en la pastora")
    _anotar(ia, db, "el jueves tengo que ir a el ombú", "El Ombú", texto="ir a vacunar", vence={"dia_semana": "jueves"})
    assert _donde(_ultimo(db)) == ("El Ombú", None)
    assert u.establecimiento_actual is not None and u.establecimiento_actual.nombre == "La Pastora"
    _mandar(db, "vacuné 30 vaquillonas")
    evento = db.scalars(select(Evento)).one()
    assert evento.nombre_establecimiento == "La Pastora"


def test_sin_campo_actual_queda_sin_campo(db, ia):
    con_perfil(db, TEL)
    r = _anotar(ia, db, "comprar ivermectina", texto="comprar ivermectina")
    assert r.startswith("📌 *PENDIENTE ANOTADO*\n\n📌 *Comprar ivermectina*\n\n")
    assert _ultimo(db).establecimiento is None


def test_sin_que_hacer_no_anota_nada(db, ia):
    con_perfil(db, TEL)
    assert _anotar(ia, db, "anotá un pendiente") == pendientes.NADA_CLARO
    assert _anotar(ia, db, "anotá un pendiente: **", texto=" *_~ ") == pendientes.NADA_CLARO
    assert _abiertos(db) == []


def test_el_texto_va_sin_simbolos_de_formato_y_hasta_120_caracteres(db, ia):
    """Un * o un _ en el texto desarmaría la negrita y la cursiva de la respuesta."""
    con_perfil(db, TEL)
    r = _anotar(ia, db, "pedir *ivermectina* y ~vacunas~", texto="pedir *ivermectina* y_vacunas ~ya~")
    assert r.startswith("📌 *PENDIENTE ANOTADO*\n\n📌 *Pedir ivermectina y vacunas ya*")
    largo = "revisar " + "aguadas " * 30
    _anotar(ia, db, "uno largo", texto=largo)
    assert _ultimo(db).texto == largo[:120].rstrip() and len(_ultimo(db).texto) <= 120


# --- Consultar ------------------------------------------------------------------------


def test_los_vencidos_van_primero_y_destacados(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en la pastora")
    _anotar(ia, db, "comprar ivermectina", texto="comprar ivermectina")
    _anotar(ia, db, "el martes reviso aguadas", texto="revisar aguadas", vence={"dia_semana": "martes"})
    _anotar(ia, db, "tenía que llamar al veterinario el lunes", texto="llamar al veterinario", vence=LUNES_PASADO)
    _anotar(ia, db, "hoy pido el camión", texto="pedir el camión", vence={"dias": 0})
    _anotar(ia, db, "el 10 tenía que pagar", texto="pagar al contratista", vence={"dia": 10, "cual": "pasado"})

    r = _mandar(db, "¿qué tengo pendiente?")
    assert r.startswith("📌 *TUS PENDIENTES*\n5 pendientes · ⚠️ 2 vencidos\n\n")
    orden = [r.index(t) for t in ("Pagar al", "Llamar al", "Pedir el", "Revisar aguadas", "Comprar")]
    assert orden == sorted(orden)
    assert "⚠️ *Pagar al contratista*\n      📍 La Pastora · *Venció el Sáb 10/10/2026*" in r
    assert "📌 *Pedir el camión*\n      📍 La Pastora · 📅 *Para hoy*" in r
    assert "📌 *Comprar ivermectina*\n      📍 La Pastora\n" in r


def test_los_pendientes_de_un_campo(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en la pastora")
    _anotar(ia, db, "comprar ivermectina", texto="comprar ivermectina")
    _anotar(ia, db, "en el ombú hay que arreglar el molino", "El Ombú", texto="arreglar el molino")
    ia["¿qué tengo pendiente en el ombú?"] = {"intencion": "ver_pendientes", "establecimiento": "el ombú"}

    r = _mandar(db, "¿qué tengo pendiente en el ombú?")
    assert r.startswith("📌 *TUS PENDIENTES*\n📍 El Ombú · 1 pendiente\n\n📌 *Arreglar el molino*\n\n")
    assert "Comprar" not in r
    ia["¿y en el retiro?"] = {"intencion": "ver_pendientes", "establecimiento": "El Retiro"}
    assert _mandar(db, "¿y en el retiro?") == "📭 No tenés nada pendiente en El Retiro."


def test_sin_pendientes(db, ia):
    con_perfil(db, TEL)
    assert _mandar(db, "¿qué tengo pendiente?") == pendientes.SIN_PENDIENTES


# --- Marcar hechos --------------------------------------------------------------------


def test_marcar_hecho_por_sus_palabras(db, ia):
    con_perfil(db, TEL)
    _anotar(ia, db, "tengo que llamar al veterinario", texto="llamar al veterinario")
    _anotar(ia, db, "comprar ivermectina", texto="comprar ivermectina")

    r = _sobre(ia, db, "pendiente_hecho", "ya llamé al vete", {"texto": "llamé al veterinario"})
    assert r.startswith("✅ *HECHO*\n\n✅ *Llamar al veterinario*")
    assert r.endswith("_Te queda 1 pendiente._")
    assert _abiertos(db) == ["comprar ivermectina"]
    hecho = db.scalars(select(Pendiente).where(Pendiente.hecho.is_not(None))).one()
    assert hecho.texto == "llamar al veterinario"  # se guarda, con la fecha en que se hizo
    assert "Llamar" not in _mandar(db, "¿qué tengo pendiente?")


def test_marcar_hecho_por_el_lote(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en la pastora")
    _anotar(ia, db, "revisar aguadas del lote 3", texto="revisar aguadas", lote="3")
    _anotar(ia, db, "revisar aguadas del lote 5", texto="revisar aguadas", lote="5")
    r = _sobre(ia, db, "pendiente_hecho", "ya está lo del lote 3", {"lote": "lote 3"})
    assert r.startswith("✅ *HECHO*\n\n✅ *Revisar aguadas*\n      Lote 3 · 📍 La Pastora")
    assert r.endswith("_Te queda 1 pendiente._")
    assert [(p.lote.nombre, p.hecho is None) for p in db.scalars(select(Pendiente).order_by(Pendiente.id))] == [
        ("3", False),
        ("5", True),
    ]


def test_si_coincide_con_varios_no_marca_ninguno(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "estoy en la pastora")
    _anotar(ia, db, "revisar aguadas del lote 3", texto="revisar aguadas", lote="3")
    _anotar(ia, db, "revisar aguadas del lote 5", texto="revisar aguadas", lote="5")

    r = _sobre(ia, db, "pendiente_hecho", "ya revisé las aguadas", {"texto": "aguadas"})
    assert r.startswith("🤔 *Hay 2 pendientes* que coinciden con _aguadas_.\nNo marqué ninguno:")
    assert "› 📌 Revisar aguadas · Lote 3 · 📍 La Pastora" in r
    assert len(_abiertos(db)) == 2

    r = _sobre(ia, db, "pendiente_hecho", "ya revisé todas las aguadas", {"texto": "aguadas", "todos": True})
    assert r.endswith("_No te queda nada pendiente._ 👌")
    assert _abiertos(db) == []


def test_si_no_encuentra_no_marca_nada(db, ia):
    con_perfil(db, TEL)
    _anotar(ia, db, "llamar al veterinario", texto="llamar al veterinario")
    r = _sobre(ia, db, "pendiente_hecho", "ya llamé a juan", {"texto": "llamar a Juan"})
    assert r == "🔍 No encontré un pendiente con _llamar a Juan_."
    assert _abiertos(db) == ["llamar al veterinario"]


def test_sin_decir_cual_muestra_las_opciones(db, ia):
    con_perfil(db, TEL)
    _anotar(ia, db, "llamar al veterinario", texto="llamar al veterinario")
    r = _sobre(ia, db, "pendiente_hecho", "ya está")
    assert r == f"{pendientes.CUAL}\n\n      › 📌 Llamar al veterinario"


# --- Borrar ---------------------------------------------------------------------------


def test_borrar_un_pendiente(db, ia):
    con_perfil(db, TEL)
    _anotar(ia, db, "llamar al veterinario", texto="llamar al veterinario")
    _anotar(ia, db, "comprar ivermectina", texto="comprar ivermectina")
    r = _sobre(ia, db, "borrar_pendiente", "borrá el pendiente de la ivermectina", {"texto": "ivermectina"})
    assert r.startswith("⚠️ *VOY A BORRAR 1 PENDIENTE*\n\n      › 📌 Comprar ivermectina")
    assert "Respondé *sí* para borrarlo" in r and len(_abiertos(db)) == 2  # pregunta antes, aunque sea uno
    assert _mandar(db, "sí") == "🗑️ *PENDIENTE BORRADO*\n\nListo, borré 1 pendiente."
    assert db.scalars(select(Pendiente.texto)).all() == ["llamar al veterinario"]


def _cuatro_molinos(ia, db) -> None:
    con_perfil(db, TEL)
    for lote in ("1", "2", "3", "4"):
        _anotar(ia, db, f"revisar el molino del lote {lote}", texto="revisar el molino", lote=lote)
    _anotar(ia, db, "llamar al veterinario", texto="llamar al veterinario")


def test_borrar_4_o_mas_pendientes_pide_confirmacion(db, ia):
    _cuatro_molinos(ia, db)
    r = _sobre(ia, db, "borrar_pendiente", "borrá todos los molinos", {"texto": "molino", "todos": True})
    assert r.startswith("⚠️ *VOY A BORRAR 4 PENDIENTES*\n\n      › 📌 Revisar el molino · Lote 1\n")
    assert "¿Confirmás? Respondé *sí*" in r
    assert len(_abiertos(db)) == 5  # todavía no borró nada

    r = _mandar(db, "sí")
    assert r == "🗑️ *PENDIENTES BORRADOS*\n\nListo, borré 4 pendientes."
    assert _abiertos(db) == ["llamar al veterinario"]


def test_borrar_4_pendientes_se_puede_cancelar(db, ia):
    _cuatro_molinos(ia, db)
    _sobre(ia, db, "borrar_pendiente", "borrá todos los molinos", {"texto": "molino", "todos": True})
    assert _mandar(db, "no") == "👌 Listo, no borré nada."
    assert len(_abiertos(db)) == 5


def test_marcar_hechos_4_o_mas_no_pide_confirmacion(db, ia):
    _cuatro_molinos(ia, db)
    r = _sobre(ia, db, "pendiente_hecho", "ya revisé todos los molinos", {"texto": "molino", "todos": True})
    assert r.startswith("✅ *HECHO*") and r.endswith("_Te queda 1 pendiente._")
    assert _abiertos(db) == ["llamar al veterinario"]


def test_borrar_deshace_lo_ultimo_que_se_anoto(db, ia):
    """`borrar` deshace lo último: un pendiente si fue lo último, si no el registro."""
    con_perfil(db, TEL)
    _mandar(db, "vacuné 30 vaquillonas")
    _anotar(ia, db, "comprar ivermectina", texto="comprar ivermectina")

    assert _mandar(db, "borrar") == "🗑️ *PENDIENTE BORRADO*\n\n🗑️ *Comprar ivermectina*"
    assert db.scalars(select(Pendiente)).all() == [] and len(db.scalars(select(Evento)).all()) == 1

    _anotar(ia, db, "comprar ivermectina", texto="comprar ivermectina")
    _mandar(db, "vacuné 30 vaquillonas")
    assert _mandar(db, "borrar").startswith("🗑️ *BORRADO*")
    assert len(db.scalars(select(Evento)).all()) == 1 and _abiertos(db) == ["comprar ivermectina"]


# --- Fechas pasadas y corregir ------------------------------------------------------


def test_un_pendiente_con_fecha_pasada_queda_vencido(db, ia):
    """ "Tenía que pagarle al contratista el lunes": la IA manda la fecha pasada y se guarda así."""
    con_perfil(db, TEL)
    r = _anotar(ia, db, "tenía que pagarle al contratista el lunes", texto="pagarle al contratista", vence=LUNES_PASADO)
    assert "*Venció el Lun 12/10/2026*" in r
    assert _ultimo(db).vence == date(2026, 10, 12)
    assert "⚠️ 1 vencido" in _mandar(db, "¿qué tengo pendiente?")


def _corregir(ia, db, mensaje, *referencias, telefono=TEL, **cambios):
    """Manda `mensaje` y la IA falsa devuelve "corregir_pendiente" con esas referencias y cambios."""
    ia[mensaje] = {
        "intencion": "corregir_pendiente",
        "correccion_pendiente": {"pendientes": list(referencias), "cambios": cambios},
    }
    return _mandar(db, mensaje, telefono)


def test_corregir_la_fecha_del_ultimo_pendiente_sin_decir_cual(db, ia):
    con_perfil(db, TEL)
    _anotar(ia, db, "llamar al veterinario", texto="llamar al veterinario")
    _anotar(ia, db, "revisar las aguadas el martes", texto="revisar las aguadas", vence={"dia_semana": "martes"})
    r = _corregir(
        ia, db, "perdón, el martes no, el jueves 22 de octubre", vence={"dia_semana": "jueves", "dia": 22, "mes": 10}
    )
    assert r.startswith("✏️ *PENDIENTE CORREGIDO*\n\n✏️ *Revisar las aguadas*\n")
    assert "📅 Para el Jue 22/10/2026" in r
    assert _ultimo(db).vence == date(2026, 10, 22)
    assert db.scalars(select(Pendiente).where(Pendiente.texto == "llamar al veterinario")).one().vence is None


def test_corregir_un_pendiente_nombrandolo(db, ia):
    con_perfil(db, TEL)
    _anotar(ia, db, "revisar las aguadas el martes", texto="revisar las aguadas", vence={"dia_semana": "martes"})
    _anotar(ia, db, "llamar al veterinario", texto="llamar al veterinario")
    r = _corregir(
        ia,
        db,
        "el pendiente de las aguadas es para el jueves 22",
        {"texto": "aguadas"},
        vence={"dia_semana": "jueves", "dia": 22},
    )
    assert r.startswith("✏️ *PENDIENTE CORREGIDO*\n\n✏️ *Revisar las aguadas*")
    assert db.scalars(select(Pendiente).where(Pendiente.texto == "revisar las aguadas")).one().vence == date(
        2026, 10, 22
    )


def test_corregir_el_texto_el_campo_y_el_lote(db, ia):
    con_perfil(db, TEL)
    _anotar(ia, db, "revisar el molino del lote 3", "La Pastora", texto="revisar el molino", lote="3")
    _corregir(ia, db, "no era en La Pastora, era en El Retiro", {"texto": "molino"}, establecimiento="El Retiro")
    assert _donde(_ultimo(db)) == ("El Retiro", "3")  # el lote 3, ahora del campo nuevo
    _corregir(ia, db, "era el lote 4 y es arreglar la bomba", lote="4", texto="arreglar la bomba")
    p = _ultimo(db)
    assert (p.texto, _donde(p)) == ("arreglar la bomba", ("El Retiro", "4"))


def test_corregir_uno_que_coincide_con_varios_muestra_las_opciones(db, ia):
    _cuatro_molinos(ia, db)
    r = _corregir(ia, db, "el del molino es para el viernes", {"texto": "molino"}, vence=VIERNES)
    assert r.startswith("🤔 *Hay 4 pendientes* que coinciden con _molino_.\nNo corregí ninguno:")
    assert all(p.vence is None for p in db.scalars(select(Pendiente)))


def test_corregir_4_o_mas_pide_confirmacion(db, ia):
    _cuatro_molinos(ia, db)
    r = _corregir(
        ia,
        db,
        "no son del Omu, son de La Feliz los molinos",
        {"texto": "molinos", "todos": True},
        establecimiento="La Feliz",
    )
    assert r.startswith("✏️ *VOY A CORREGIR 4 PENDIENTES*\n\n      › 📌 Revisar el molino · Lote 1\n")
    assert "*Van a quedar:* 📍 La Feliz" in r and "¿Confirmás? Respondé *sí*" in r
    assert all(p.establecimiento is None for p in db.scalars(select(Pendiente)))  # todavía nada

    assert _mandar(db, "dale") == "✏️ *PENDIENTES CORREGIDOS*\n\nListo, corregí 4 pendientes."
    molinos = db.scalars(select(Pendiente).where(Pendiente.texto == "revisar el molino")).all()
    assert [_donde(p) for p in molinos] == [("La Feliz", lote) for lote in ("1", "2", "3", "4")]


def test_corregir_4_o_mas_se_puede_cancelar(db, ia):
    _cuatro_molinos(ia, db)
    _corregir(
        ia, db, "los molinos son para el lunes", {"texto": "molino", "todos": True}, vence={"dia_semana": "lunes"}
    )
    assert _mandar(db, "no, dejá") == "👌 Listo, no cambié nada."
    assert all(p.vence is None for p in db.scalars(select(Pendiente)))


def test_corregir_sin_cambios_o_sin_pendientes(db, ia):
    con_perfil(db, TEL)
    assert _corregir(ia, db, "corregí el pendiente") == pendientes.SIN_CAMBIOS
    assert _corregir(ia, db, "el último es para el viernes", vence=VIERNES) == pendientes.SIN_PENDIENTES
    _anotar(ia, db, "llamar al veterinario", texto="llamar al veterinario")
    _sobre(ia, db, "pendiente_hecho", "ya llamé", {"texto": "veterinario"})
    # El último ya está hecho: no se toca, y no queda ninguno abierto.
    assert _corregir(ia, db, "era para el viernes", vence=VIERNES) == pendientes.SIN_PENDIENTES


# --- Cada cuenta con lo suyo -------------------------------------------------------


def test_cada_persona_ve_y_toca_solo_sus_pendientes(db, ia):
    con_perfil(db, TEL)
    con_perfil(db, OTRO)
    _anotar(ia, db, "llamar al veterinario", texto="llamar al veterinario")

    assert _mandar(db, "¿qué tengo pendiente?", telefono=OTRO) == pendientes.SIN_PENDIENTES
    r = _sobre(ia, db, "pendiente_hecho", "ya llamé", {"texto": "veterinario"}, telefono=OTRO)
    assert r.startswith("🔍 No encontré")
    r = _sobre(ia, db, "borrar_pendiente", "borralo", {"texto": "veterinario"}, telefono=OTRO)
    assert r.startswith("🔍 No encontré")
    r = _corregir(ia, db, "es para el viernes", {"texto": "veterinario"}, telefono=OTRO, vence=VIERNES)
    assert r.startswith("🔍 No encontré")
    assert _corregir(ia, db, "el último es para el lunes", telefono=OTRO, vence={"dia_semana": "lunes"}) == (
        pendientes.SIN_PENDIENTES
    )
    assert _mandar(db, "borrar", telefono=OTRO) == "📭 No tenés nada anotado para borrar."
    assert _abiertos(db) == ["llamar al veterinario"]
