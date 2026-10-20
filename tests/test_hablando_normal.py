"""Todo se pide hablando normal (principio 7 del plan).

Los comandos escritos son atajos: exactos, sin IA. Pedido con otras palabras, la IA reconoce
la función y la deriva al mismo manejador, con la misma respuesta. Estos tests usan una IA
falsa: que la IA real reconozca las frases se mide con el set de evaluación
(`evaluacion/set.json`).
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.ia import interprete
from app.infra.modelos import MensajeChat, Usuario
from app.modulos.comun import conversacion
from app.nucleo import acciones, pipeline, preguntas
from tests.ayudas import con_perfil

HOY = date(2026, 10, 15)
TEL, OTRO = "5491100000001", "5491100000002"
SET = Path(__file__).parent.parent / "evaluacion" / "set.json"

# Las funciones que se piden hablando y las intenciones con que llegan.
FUNCIONES = {
    "mis_campos": "mis_campos",
    "mis_datos": "mis_datos",
    "cambiar_rubro": "cambiar_rubro",
    "cambiar_matricula": "cambiar_matricula",
    "privacidad": "privacidad",
    "ayuda": "ayuda",
    "borrar_ultimo": "borrar",
    "cerrar_sesion": "cerrar_sesion",
    "ver_pendientes": "ver_pendientes",
    "anotar_pendiente": "anotar_pendiente",
    "pendiente_hecho": "pendiente_hecho",
    "borrar_pendiente": "borrar_pendiente",
    "corregir_pendiente": "corregir_pendiente",
    "cancelar": "cancelar",
    "borrar_mis_datos": "borrar_mis_datos",
    "exportar_pdf": "exportar",
    "exportar_excel": "exportar",
    "exportar_csv": "exportar",
    "renombrar_campo": "renombrar_campo",
    "unir_campos": "renombrar_campo",
    "renombrar_lote": "renombrar_campo",
    "borrar_campo": "borrar_campo",
}
ADMINISTRADOR = {"invitar", "invitaciones", "anular", "autorizar", "quitar", "autorizados"}


@pytest.fixture
def ia(monkeypatch):
    """La IA falsa: cada texto tiene su respuesta. `llamadas` cuenta cuántas veces se usó."""
    respuestas: dict[str, object] = {
        "estoy en la pastora": {"intencion": "establecimiento", "establecimiento": "La Pastora"},
        "vacuné 30 vaquillonas": {
            "intencion": "registrar",
            "eventos": [{"categoria": "sanidad", "tipo": "vacunacion", "cantidad_animales": 30}],
        },
        "arranco manga en el retiro lote 3": {
            "intencion": "abrir_sesion",
            "establecimiento": "El Retiro",
            "sesion": {"lote": "3", "actividad": "manga"},
        },
        "acordate de llamar al veterinario": {
            "intencion": "anotar_pendiente",
            "pendiente": {"texto": "llamar al veterinario"},
        },
    }
    llamadas: list[str] = []

    def interpretar(texto, *_a, **_k):
        llamadas.append(texto)
        return respuestas[texto]

    monkeypatch.setattr(pipeline, "_ahora", lambda: datetime(2026, 10, 15, 12, 0, tzinfo=UTC))
    monkeypatch.setattr(interprete, "interpretar", interpretar)
    return respuestas, llamadas


def _mandar(db, texto, telefono=TEL):
    return pipeline.manejar_mensaje(db, telefono, texto, hoy=HOY)


def _con_cosas(db, telefono):
    """Una persona con un campo, un registro, una sesión abierta y un pendiente."""
    con_perfil(db, telefono)
    for texto in (
        "estoy en la pastora",
        "vacuné 30 vaquillonas",
        "arranco manga en el retiro lote 3",
        "acordate de llamar al veterinario",
        "vacuné 30 vaquillonas",
    ):
        _mandar(db, texto, telefono)


# --- El set de evaluación ---------------------------------------------------------------


def _frases() -> list[dict]:
    frases: list[dict] = json.loads(SET.read_text(encoding="utf-8"))["frases"]
    return frases


@pytest.mark.parametrize("funcion", list(FUNCIONES))
def test_el_set_tiene_al_menos_5_formas_de_pedir_cada_funcion(funcion):
    frases = {f["frase"].lower() for f in _frases() if f["funcion"] == funcion}
    assert len(frases) >= 5
    assert all(f["intenciones"] == [FUNCIONES[funcion]] for f in _frases() if f["funcion"] == funcion)


def test_el_set_solo_espera_intenciones_que_existen():
    esperadas = {i for f in _frases() for i in f["intenciones"]}
    assert esperadas <= {*acciones.intenciones(), "fuera_de_alcance"}


def test_las_preguntas_pendientes_del_set_existen():
    assert {f["pregunta"] for f in _frases() if "pregunta" in f} <= set(preguntas.PREGUNTAS)


def test_los_comandos_del_administrador_no_son_intenciones_de_la_ia():
    """Solo exactos y escritos: la IA no los puede pedir."""
    assert not ADMINISTRADOR & set(acciones.intenciones())


# --- Atajo o frase: la misma respuesta --------------------------------------------------

# (atajo, intención que devuelve la IA para una frase con otras palabras)
ATAJOS = [
    ("ayuda", {"intencion": "ayuda"}),
    ("privacidad", {"intencion": "privacidad"}),
    ("mis campos", {"intencion": "mis_campos"}),
    ("mis datos", {"intencion": "mis_datos"}),
    ("cambiar rubro", {"intencion": "cambiar_rubro"}),
    ("cambiar matrícula", {"intencion": "cambiar_matricula"}),
    ("borrar", {"intencion": "borrar", "borrado": {"registros": []}}),
    ("cerrar sesión", {"intencion": "cerrar_sesion"}),
    ("borrar mis datos", {"intencion": "borrar_mis_datos"}),
]


@pytest.mark.parametrize(("atajo", "interpretado"), ATAJOS, ids=[a for a, _ in ATAJOS])
def test_pedido_con_otras_palabras_responde_igual_que_el_atajo(db, ia, atajo, interpretado):
    respuestas, llamadas = ia
    _con_cosas(db, TEL)
    _con_cosas(db, OTRO)
    antes = len(llamadas)

    por_atajo = _mandar(db, atajo, TEL)
    assert len(llamadas) == antes  # el atajo no pasa por la IA

    respuestas["che, una frase cualquiera"] = interpretado
    por_frase = _mandar(db, "che, una frase cualquiera", OTRO)
    assert len(llamadas) == antes + 1
    assert por_frase == por_atajo


def test_los_atajos_aceptan_signos_tildes_y_mayusculas(db, ia):
    _, llamadas = ia
    con_perfil(db, TEL)
    assert _mandar(db, "¿Ayuda?") == _mandar(db, "ayuda")
    assert _mandar(db, "Mis Campos!") == _mandar(db, "mis campos")
    assert llamadas == []


def test_cambiar_rubro_pedido_hablando_espera_la_respuesta(db, ia):
    respuestas, _ = ia
    con_perfil(db, TEL)
    respuestas["me pusiste mal el rubro"] = {"intencion": "cambiar_rubro"}
    assert "¿A qué te dedicás?" in _mandar(db, "me pusiste mal el rubro")
    assert _mandar(db, "2") == "✅ Listo, ahora figurás como *Agrónomo o asesor*."


def test_mis_datos_pedido_hablando_no_queda_en_la_charla(db, ia):
    """La respuesta trae nombre, localidad y matrícula: la IA no los necesita."""
    respuestas, _ = ia
    con_perfil(db, TEL)
    respuestas["pasame mis datos"] = {"intencion": "mis_datos"}
    assert _mandar(db, "pasame mis datos").startswith("👤 *MIS DATOS*")
    assert db.scalars(select(MensajeChat)).all() == []


def test_varios_pedidos_juntos(db, ia):
    respuestas, _ = ia
    _con_cosas(db, TEL)
    respuestas["mostrame mis campos y qué tengo pendiente"] = {
        "acciones": [{"intencion": "mis_campos"}, {"intencion": "ver_pendientes"}]
    }
    r = _mandar(db, "mostrame mis campos y qué tengo pendiente")
    campos, pendientes = r.split(pipeline.SEPARADOR)
    assert campos == _mandar(db, "mis campos")
    assert pendientes.startswith("📌 *TUS PENDIENTES*")


def test_si_no_se_entiende_que_pide_pregunta(db, ia):
    respuestas, _ = ia
    con_perfil(db, TEL)
    respuestas["ehh mostrame eso"] = {"intencion": "aclarar", "falta": ["que_pedido"]}
    r = _mandar(db, "ehh mostrame eso")
    assert r == conversacion.repreguntar("que_pedido") and r.startswith("🤔 ¿Qué necesitás?")


# --- Excepción: borrar mis datos ---------------------------------------------------------


def test_borrar_mis_datos_hablando_solo_muestra_el_aviso(db, ia):
    """Borrar exige escribir exacto "confirmo borrar mis datos"; nada que diga la IA borra."""
    respuestas, _ = ia
    con_perfil(db, TEL)
    respuestas["dame de baja"] = {"intencion": "borrar_mis_datos"}
    respuestas["sí, confirmo, borralo todo"] = {"intencion": "borrar_mis_datos"}

    assert _mandar(db, "dame de baja").startswith("⚠️ *BORRAR TODOS TUS DATOS*")
    assert _mandar(db, "sí, confirmo, borralo todo").startswith("⚠️ *BORRAR TODOS TUS DATOS*")
    assert db.scalar(select(Usuario).where(Usuario.telefono == TEL)) is not None

    assert _mandar(db, "confirmo borrar mis datos").startswith("🗑️ *DATOS BORRADOS*")
    assert db.scalar(select(Usuario).where(Usuario.telefono == TEL)) is None
