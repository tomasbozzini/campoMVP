"""Un nombre de intención casi igual a uno válido se toma como ese (paso 2 de la etapa 2).

En una muestra del paso 1 la IA devolvió dos veces "borrar_pendente" y el bot respondió que
eso no lo hacía. El umbral es alto: una letra de más, de menos o cambiada en un nombre largo;
lo que se parece a dos intenciones no se toma como ninguna.
"""

from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from itertools import combinations

import pytest
from sqlalchemy import select

from app import modulos
from app.ia import evaluacion, interprete
from app.ia.esquemas import PARECIDO_INTENCION, intencion_valida
from app.infra.modelos import Pendiente
from app.nucleo import acciones, pipeline
from app.nucleo.cuaderno import Cuaderno
from tests.ayudas import con_perfil
from tests.test_eval import IAFalsa

HOY = date(2026, 10, 20)
TEL = "5491100000001"
AHORA = datetime(2026, 10, 20, 17, 32, tzinfo=UTC)


@pytest.mark.parametrize(
    ("nombre", "valida"),
    [
        ("borrar_pendente", "borrar_pendiente"),  # el de la muestra del paso 1
        ("borrar_pendientes", "borrar_pendiente"),
        ("Borrar pendiente", "borrar_pendiente"),
        ("borrar-pendiente", "borrar_pendiente"),
        ("  saludo ", "saludo"),
        ("cerrar_sesión", "cerrar_sesion"),
        ("ver_pendiente", "ver_pendientes"),
        ("pendiente_hecha", "pendiente_hecho"),
        ("precios", "precio"),
        ("consulta", "consultar"),
        ("producto_veterinaro", "producto_veterinario"),
    ],
)
def test_un_nombre_casi_igual_se_toma_como_ese(nombre, valida):
    assert intencion_valida(nombre, acciones.intenciones()) == valida


@pytest.mark.parametrize(
    "nombre",
    ["registro", "borrar_datos", "borrar_todo", "anotar", "fuera_de_alcance", "ecografia", "", None, 3, ["borrar"]],
)
def test_lo_que_no_se_parece_bastante_no_es_ninguna(nombre):
    assert intencion_valida(nombre, acciones.intenciones()) is None


def test_lo_que_se_parece_a_dos_no_es_ninguna():
    assert intencion_valida("unir_lotez", ["unir_lote", "unir_lotes"]) is None
    assert intencion_valida("unir_lotez", ["unir_lote"]) == "unir_lote"


def test_dos_intenciones_validas_no_se_parecen_tanto():
    """Si dos se parecieran tanto, un nombre mal escrito podría ser cualquiera de las dos. Al
    sumar una intención, este test avisa si choca con otra."""
    for a, b in combinations(acciones.intenciones(), 2):
        assert SequenceMatcher(None, a, b).ratio() < PARECIDO_INTENCION, (a, b)


@pytest.fixture
def ia(monkeypatch):
    dichas = {
        "borrá el pendiente del molino": {"intencion": "borrar_pendente", "pendientes": [{"texto": "molino"}]},
        "sí": {"acciones": [{"intencion": "aclarar"}]},  # no llega: el sí lo contesta el código
    }
    monkeypatch.setattr(pipeline, "_ahora", lambda: AHORA)
    monkeypatch.setattr(interprete, "interpretar", lambda texto, *_a, **_k: dichas[texto])


def test_un_borrado_con_el_nombre_casi_igual_igual_pide_confirmacion(db, ia):
    usuario = con_perfil(db, TEL)
    Cuaderno(db, usuario).agregar_pendiente(Pendiente(texto="revisar el molino"))
    db.commit()
    respuesta = pipeline.manejar_mensaje(db, TEL, "borrá el pendiente del molino", hoy=HOY)
    assert "VOY A BORRAR 1 PENDIENTE" in respuesta and "Revisar el molino" in respuesta
    assert len(db.scalars(select(Pendiente)).all()) == 1  # todavía no borró nada
    assert pipeline.manejar_mensaje(db, TEL, "sí", hoy=HOY) == "🗑️ *PENDIENTE BORRADO*\n\nListo, borré 1 pendiente."
    assert db.scalars(select(Pendiente)).all() == []


def test_la_evaluacion_cuenta_el_nombre_casi_igual_como_el_bot():
    frase = evaluacion.Frase("borrar_pendiente", "borrá el pendiente del molino", ("borrar_pendiente",))
    ia = IAFalsa({frase.frase: {"acciones": [{"intencion": "borrar_pendente"}]}})
    resultados, _ = evaluacion.correr([frase], ia, modulos.partes(["comun"]), HOY, tope_usd=1.0)
    assert resultados[0].obtenidas == ("borrar_pendiente",) and resultados[0].bien
    # Se informa aparte, para ver si la IA los escribe mal más seguido.
    assert resultados[0].corregidas == (("borrar_pendente", "borrar_pendiente"),)
    assert evaluacion.resumir(resultados).corregidas == 1
    assert evaluacion.intenciones({"intencion": "borrar_pendente"}) == ("borrar_pendente",)  # sin las válidas, tal cual
