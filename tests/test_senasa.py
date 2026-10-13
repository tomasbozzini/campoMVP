"""Tests del registro de SENASA. No salen a internet.

La lectura del Excel que devuelve la exportación no se prueba acá (haría falta guardar
un fixture binario de 1,2 MB): lo que se prueba es el armado del formulario público y
todos los controles que hacen fallar la carga si la página cambia.
"""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import senasa
from app.db import Base
from app.models import ProductoVeterinario

FIXTURES = Path(__file__).parent / "fixtures"
FECHA = date(2026, 10, 11)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as sesion:
        yield sesion


@pytest.fixture
def formulario() -> str:
    return (FIXTURES / "senasa_consulta_publica.html").read_bytes().decode("ISO-8859-1")


FILAS = [
    {
        "nombre": "IVERMECTINA 1% ROSENBUSCH",
        "registro": "04-125",
        "titular": "INSTITUTO ROSENBUSCH S A",
        "principio_activo": None,
        "estado": None,
    },
    {
        "nombre": "PODOCUR ANTIPIETIN",
        "registro": "00-001",
        "titular": "HYPRED ARGENTINA S A",
        "principio_activo": None,
        "estado": None,
    },
]


class _ClienteFalso:
    """Imita httpx.Client: devuelve el formulario real y una exportación a elección."""

    def __init__(self, formulario: str, exportacion: bytes):
        self._formulario = formulario.encode("ISO-8859-1")
        self._exportacion = exportacion
        self.posts = 0

    class _Respuesta:
        def __init__(self, content):
            self.content = content

    def get(self, url, **kwargs):
        return self._Respuesta(self._formulario)

    def post(self, url, data=None, **kwargs):
        self.posts += 1
        # El primer POST es "Consultar"; el segundo, "Exportar a CSV".
        if self.posts == 1:
            assert data["Formulario:cmdConsultarProductos"] == "Consultar"
            return self._Respuesta(self._formulario)
        assert data["Formulario:exportarConsultaACSV"] == "Exportar a CSV"
        return self._Respuesta(self._exportacion)


# --- Formulario público -----------------------------------------------------


def test_campos_del_formulario_lleva_el_estado_jsf_y_los_filtros_vacios(formulario):
    campos = senasa._campos_del_formulario(formulario)
    for obligatorio in ("jsf_tree_64", "jsf_state_64", "jsf_viewid"):
        assert campos[obligatorio], obligatorio
    assert campos["Formulario_SUBMIT"] == "1"
    # Los cuatro filtros van vacíos para traer todo el registro.
    assert [campos[f"Formulario:{c}"] for c in senasa.CAMPOS_BUSQUEDA] == ["", "", "", ""]


def test_campos_del_formulario_falla_si_la_pagina_cambio(formulario):
    with pytest.raises(ValueError, match="estado del formulario"):
        senasa._campos_del_formulario(formulario.replace("jsf_state_64", "otra_cosa"))


def test_descargar_falla_si_la_exportacion_no_es_un_excel(formulario):
    cliente = _ClienteFalso(formulario, b"nombre,registro\nalgo,1\n")
    with pytest.raises(ValueError, match="no es un Excel"):
        senasa.descargar(cliente)  # type: ignore[arg-type]
    assert cliente.posts == 2  # consultó y exportó antes de darse cuenta


# --- Carga y respuesta ------------------------------------------------------


def test_la_url_oficial_es_gob_ar_y_la_de_la_consulta_no_pasa(db):
    # El registro se guarda con la página .gob.ar; aps2.senasa.gov.ar no está permitido.
    assert senasa.reemplazar_registro(db, FILAS, FECHA, senasa.URL_OFICIAL) == 2
    with pytest.raises(ValueError, match="no es de un organismo oficial"):
        senasa.reemplazar_registro(db, FILAS, FECHA, senasa.URL_CONSULTA)


def test_sin_principio_activo_ni_estado_dice_no_informado(db):
    senasa.reemplazar_registro(db, FILAS, FECHA, senasa.URL_OFICIAL)
    respuesta = senasa.responder(db, "ivermectina")
    assert "*IVERMECTINA 1% ROSENBUSCH*" in respuesta
    assert "N° de registro: *04-125*" in respuesta
    assert "Estado: no informado" in respuesta
    # No inventa un principio activo que la consulta pública no publica.
    assert "🧪" not in respuesta
    assert f"datos al {FECHA.strftime('%d/%m/%Y')}" in respuesta
    assert senasa.URL_OFICIAL in respuesta
    assert senasa.AVISO in respuesta


def test_producto_que_no_aparece_no_se_declara_no_registrado(db):
    senasa.reemplazar_registro(db, FILAS, FECHA, senasa.URL_OFICIAL)
    respuesta = senasa.responder(db, "zzzinexistente")
    assert "No encontré ese producto" in respuesta
    assert "no confirma que no esté registrado" in respuesta


def test_sin_registro_cargado_lo_aclara(db):
    assert "Todavía no tengo cargado" in senasa.responder(db, "ivermectina")


def test_una_carga_reemplaza_la_anterior_entera(db):
    senasa.reemplazar_registro(db, FILAS, FECHA, senasa.URL_OFICIAL)
    senasa.reemplazar_registro(db, FILAS[:1], date(2026, 10, 12), senasa.URL_OFICIAL)
    quedaron = db.scalars(select(ProductoVeterinario)).all()
    assert [p.registro for p in quedaron] == ["04-125"]
    assert quedaron[0].fecha_datos == date(2026, 10, 12)


def test_una_carga_vacia_no_borra_el_registro(db):
    senasa.reemplazar_registro(db, FILAS, FECHA, senasa.URL_OFICIAL)
    with pytest.raises(ValueError, match="no se toca el registro actual"):
        senasa.reemplazar_registro(db, [], FECHA, senasa.URL_OFICIAL)
    assert len(db.scalars(select(ProductoVeterinario)).all()) == 2
