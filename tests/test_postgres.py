"""Postgres: la URL que entrega Railway funciona con el driver instalado."""

from sqlalchemy import create_engine

from app.infra.config import Configuracion


def test_la_url_de_railway_carga_el_driver_de_postgres():
    url = Configuracion(_env_file=None, database_url="postgres://u:c@host:5432/base").database_url
    motor = create_engine(url)  # carga el driver, sin conectarse
    assert motor.dialect.name == "postgresql"
