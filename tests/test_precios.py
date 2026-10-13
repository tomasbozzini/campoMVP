"""Tests de los lectores de precios: leen los HTML de fixtures/, nunca internet.

Los fixtures son la respuesta tal cual la sirvió cada página, con su encoding original,
así que estos tests también cubren la decodificación.
"""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fuentes import oficiales, precios
from app.infra.db import Base
from app.modulos.comun import precios as respuesta_precios

FIXTURES = Path(__file__).parent / "fixtures"
HOY = date(2026, 10, 11)


def _fixture(nombre: str, encoding: str) -> str:
    return (FIXTURES / nombre).read_bytes().decode(encoding)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as sesion:
        yield sesion


@pytest.fixture
def pizarra() -> list[dict]:
    return precios.PizarraRosario().leer(_fixture("cac_pizarra.html", "utf-8"))


@pytest.fixture
def hacienda() -> list[dict]:
    return precios.HaciendaCanuelas().leer(_fixture("mag_precios_categoria.html", "windows-1252"))


# --- Cámara Arbitral de Cereales (Rosario) ----------------------------------


def test_pizarra_lee_los_cinco_granos(pizarra):
    assert {p["producto"]: p["valor"] for p in pizarra} == {
        "Trigo": 342700.0,
        "Maíz": 293500.0,
        "Girasol": 798440.0,
        "Soja": 560000.0,
        "Sorgo": 295300.0,
    }


def test_pizarra_usa_la_fecha_de_publicacion_no_la_de_hoy(pizarra):
    # La página dice "Precios Pizarra del día 08/10/2026" aunque se generó el 09/10.
    assert {p["fecha"] for p in pizarra} == {date(2026, 10, 8)}


def test_pizarra_moneda_unidad_y_plaza(pizarra):
    for p in pizarra:
        assert (p["moneda"], p["unidad"], p["plaza"]) == ("ARS", "t", "Rosario")
        # La página no dice nada de impuestos: queda sin informar, no en False.
        assert p["incluye_impuestos"] is None
        assert "puesto sobre camión y/o vagón en zona Rosario" in p["costos_adicionales"]
        assert "no aclara si incluye impuestos" in p["costos_adicionales"]


def test_pizarra_marca_los_estimados_sin_cotizacion(pizarra):
    # Girasol y sorgo ese día estaban S/C y la Cámara publicó un estimado (E).
    con_estimado = {p["producto"] for p in pizarra if "(E)" in p["costos_adicionales"]}
    assert con_estimado == {"Girasol", "Sorgo"}
    assert "Sin cotización (S/C)" in next(p["costos_adicionales"] for p in pizarra if p["producto"] == "Girasol")


def test_pizarra_sin_cotizacion_ni_estimado_se_saltea():
    pagina = _fixture("cac_pizarra.html", "utf-8").replace(
        '<span class="price-sc-estimated"> (E) $798.440,00</span>', ""
    )
    assert "Girasol" not in {p["producto"] for p in precios.PizarraRosario().leer(pagina)}


def test_pizarra_falla_si_la_pagina_cambio():
    entera = _fixture("cac_pizarra.html", "utf-8")
    with pytest.raises(ValueError, match="fecha"):
        precios.PizarraRosario().leer(entera.replace("Precios Pizarra del día", "Precios"))
    with pytest.raises(ValueError, match="condiciones"):
        precios.PizarraRosario().leer(entera.replace("price-board-footer", "otra-cosa"))
    with pytest.raises(ValueError, match="ningún precio"):
        precios.PizarraRosario().leer(entera.replace('class="board board-', 'class="x x-'))


# --- Mercado Agroganadero de Cañuelas ---------------------------------------


def test_hacienda_promedios_por_categoria(hacienda):
    assert {p["producto"]: p["valor"] for p in hacienda} == {
        "NOVILLOS": 4448.534,
        "NOVILLITOS": 4457.555,
        "VAQUILLONAS": 4545.383,
        "VACAS": 3076.979,
        "TOROS": 3582.670,
        "MEJ": 3800.000,
    }


def test_hacienda_fecha_de_la_rueda_unidad_y_plaza(hacienda):
    for p in hacienda:
        assert p["fecha"] == date(2026, 10, 9)  # la rueda del viernes, no el día de hoy
        assert (p["moneda"], p["unidad"], p["plaza"]) == ("ARS", "kg vivo", "Cañuelas")
        assert p["incluye_impuestos"] is None
        assert "Precios definitivos" in p["costos_adicionales"]
        assert "RESOL-2018-32-APN-SGA#MPYT" in p["costos_adicionales"]


def test_hacienda_dia_sin_operaciones_no_devuelve_nada():
    # Domingo: la planilla existe pero viene vacía. No es un error.
    assert precios.HaciendaCanuelas().leer(_fixture("mag_sin_operaciones.html", "windows-1252")) == []


def test_hacienda_falla_si_el_promedio_no_cierra_con_importe_sobre_kilos():
    pagina = _fixture("mag_precios_categoria.html", "windows-1252").replace("4.448,534", "5.100,000")
    with pytest.raises(ValueError, match="no coincide con importe/kilos"):
        precios.HaciendaCanuelas().leer(pagina)


def test_hacienda_falla_si_la_pagina_cambio():
    pagina = _fixture("mag_precios_categoria.html", "windows-1252").replace("PRECIOS POR CATEGORIA", "PRECIOS")
    with pytest.raises(ValueError, match="encabezado"):
        precios.HaciendaCanuelas().leer(pagina)


# --- Números, dominios y respuesta final ------------------------------------


def test_numeros_en_formato_argentino():
    assert precios._a_numero("$560.000,00") == 560000.0
    assert precios._a_numero("4448,534") == 4448.534
    assert precios._a_numero("4.448,534") == 4448.534
    assert precios._a_numero("1.389") == 1389.0
    for basura in ("-------", "", "S/C", "$"):
        with pytest.raises(ValueError):
            precios._a_numero(basura)


def test_las_urls_de_las_fuentes_son_oficiales_y_https():
    assert [f.nombre for f in precios.FUENTES]  # no quedó vacía
    for fuente in precios.FUENTES:
        assert fuente.url.startswith("https://")
        assert oficiales.es_oficial(fuente.url), fuente.url
        assert fuente.rubro in ("granos", "hacienda")


def test_responder_con_los_datos_de_los_fixtures(db, pizarra, hacienda):
    rosario = precios.PizarraRosario()
    canuelas = precios.HaciendaCanuelas()
    assert precios.guardar(db, rosario.nombre, rosario.url, rosario.rubro, pizarra) == 5
    assert precios.guardar(db, canuelas.nombre, canuelas.url, canuelas.rubro, hacienda) == 6

    soja = respuesta_precios.responder(db, "soja", None, HOY)
    assert "🫘 *Soja* · Rosario\n      *$ 560.000* por t (ARS)" in soja
    assert "Publicado el 08/10/2026" in soja
    assert "https://www.cac.bcr.com.ar/es/precios-de-pizarra" in soja
    assert respuesta_precios.AVISO in soja

    novillo = respuesta_precios.responder(db, "novillo", None, HOY)
    assert "🐂 *Novillo* · Cañuelas\n      *$ 4.448,53* por kg vivo (ARS)" in novillo
    assert "Publicado el 09/10/2026" in novillo
    # "novillo" no tiene que traer los novillitos
    assert "Novillito" not in novillo


def test_responder_sin_datos_no_inventa(db):
    respuesta = respuesta_precios.responder(db, "quinoa", None, HOY)
    assert "No tengo precios cargados" in respuesta
    assert "$" not in respuesta
