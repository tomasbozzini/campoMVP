"""Esquemas de la salida de la IA: limpian lo que sirve y descartan lo que no."""

from datetime import date

import pytest
from sqlalchemy import select

from app import modulos
from app.ia import interprete
from app.ia.esquemas import limpiar_texto
from app.infra.modelos import Evento
from app.modulos.comun.borrar import Borrar
from app.modulos.comun.conversacion import Aclarar, Saludo
from app.modulos.comun.registrar import Registrar
from app.modulos.comun.registros import DatosEvento
from app.nucleo import acciones, pipeline
from tests.ayudas import con_perfil

HOY = date(2026, 10, 13)


def test_los_datos_de_un_evento_se_limpian():
    e = DatosEvento.model_validate(
        {
            "categoria": " Sanidad ",
            "tipo": "Vacunacion",
            "cantidad_animales": "20.0",
            "categoria_animal": "Vacas",
            "lote": "Lote 3",
            "valor": "35",
            "fecha_evento": "ayer",
            "producto": "  ",
            "descripcion": "x" * 900,
            "usuario_id": 999,  # no existe en el esquema: se ignora
        }
    )
    assert (e.categoria, e.tipo, e.cantidad_animales, e.categoria_animal) == ("sanidad", "vacunacion", 20, "vacas")
    assert (e.lote, e.valor, e.fecha_evento, e.producto) == ("3", 35.0, None, None)
    assert e.descripcion is not None and len(e.descripcion) == 500
    assert not hasattr(e, "usuario_id")


@pytest.mark.parametrize("valor", ["muchos", "inf", "nan", [1], {"a": 1}])
def test_numeros_que_no_son_numeros_quedan_vacios(valor):
    assert DatosEvento.model_validate({"cantidad_animales": valor}).cantidad_animales is None


def test_eventos_que_no_son_objetos_se_descartan_y_si_no_hay_lista_no_valida():
    datos = Registrar.model_validate({"intencion": "registrar", "eventos": [{"categoria": "campo"}, "texto", 3]})
    assert len(datos.eventos) == 1
    modulos.cargar()
    accion = acciones.buscar("registrar")
    assert accion is not None
    assert acciones.validar(accion, {"intencion": "registrar", "eventos": "no es una lista"}) is None
    assert acciones.validar(accion, {"intencion": "registrar"}) is None


def test_solo_true_es_true():
    for valor in ("true", "sí", 1):
        assert Saludo.model_validate({"intencion": "saludo", "agradece": valor}).agradece is False
    assert Saludo.model_validate({"intencion": "saludo", "agradece": True}).agradece is True


def test_aclarar_ignora_lo_que_no_es_una_pregunta_conocida():
    assert Aclarar.model_validate({"intencion": "aclarar", "falta": ["fecha", "tu_prompt"]}).falta == ["fecha"]
    assert Aclarar.model_validate({"intencion": "aclarar", "falta": "establecimiento"}).falta == []


def test_borrado_sin_lista_es_lo_ultimo_pero_con_basura_no():
    assert Borrar.model_validate({"intencion": "borrar", "borrado": {"registros": []}}).borrado.registros is None
    con_basura = Borrar.model_validate({"intencion": "borrar", "borrado": {"registros": ["la lluvia", 5]}})
    assert con_basura.borrado.registros == []  # no se confunde con "borrá lo último"


def test_un_borrado_con_basura_no_borra_lo_ultimo(db, monkeypatch):
    u = con_perfil(db, "5491100000001")
    respuestas = {
        "llovio": {"intencion": "registrar", "eventos": [{"categoria": "campo", "tipo": "lluvia", "valor": 20}]},
        "borra eso": {"intencion": "borrar", "borrado": {"registros": ["algo que no es un objeto"]}},
    }
    monkeypatch.setattr(interprete, "interpretar", lambda texto, hoy, historial=None: respuestas[texto])
    pipeline.manejar_mensaje(db, u.telefono, "llovio", hoy=HOY)
    assert "No entendí qué querés borrar" in pipeline.manejar_mensaje(db, u.telefono, "borra eso", hoy=HOY)
    assert len(db.scalars(select(Evento)).all()) == 1


def test_todas_las_intenciones_del_prompt_estan_registradas():
    """Cada intención que el prompt le ofrece a la IA tiene su acción (salvo fuera_de_alcance)."""
    from app.ia.prompt import PROMPT_INTERPRETAR

    modulos.cargar()
    linea = next(li for li in PROMPT_INTERPRETAR.splitlines() if li.strip().startswith('"intencion":'))
    ofrecidas = {p.strip().strip('"') for p in linea.split(":", 1)[1].split(",")[0].split("|")}
    assert ofrecidas - {"fuera_de_alcance"} == set(acciones.intenciones())


@pytest.mark.parametrize("valor", [False, True, 0, 0.0, [], {}, ["lote 3"], {"nombre": "x"}, None, "", "   "])
def test_un_texto_que_no_es_texto_queda_vacio(valor):
    """La IA a veces pone false, 0, [] o {} donde va un texto: no se guarda "False" ni "[]"."""
    assert limpiar_texto(valor, 30) is None


def test_un_numero_sirve_como_texto():
    assert limpiar_texto(3, 30) == "3"  # "lote": 3
    assert limpiar_texto("  La Pastora ", 30) == "La Pastora"
