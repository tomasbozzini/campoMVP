import os

import pytest
from sqlalchemy import Engine, MetaData
from sqlalchemy.orm import sessionmaker

from app.infra.config import Configuracion, config
from app.infra.db import Base, crear_motor

# Con TEST_DATABASE_URL los tests corren sobre esa base (en el CI, un Postgres) en vez de
# SQLite. Se borran todas sus tablas: usá una base solo para esto.
URL_DE_PRUEBA = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def configuracion_de_prueba(monkeypatch):
    """Los tests no leen el .env ni las variables de entorno de la compu: parten de los
    valores por defecto, en desarrollo. Los que prueban la lectura del entorno las definen."""
    for variable in list(os.environ):
        if variable.lower() in Configuracion.model_fields:
            monkeypatch.delenv(variable)
    limpia = Configuracion(_env_file=None, entorno="desarrollo")
    for campo in Configuracion.model_fields:
        monkeypatch.setattr(config, campo, getattr(limpia, campo))


def _vaciar(engine: Engine) -> None:
    tablas = MetaData()
    tablas.reflect(engine)
    tablas.drop_all(engine)


@pytest.fixture
def motor(tmp_path):
    """Una base vacía para el test: SQLite en un archivo temporal, o la de TEST_DATABASE_URL."""
    if not URL_DE_PRUEBA:
        engine = crear_motor(f"sqlite:///{tmp_path}/prueba.db")
        yield engine
        engine.dispose()
        return
    engine = crear_motor(URL_DE_PRUEBA)
    _vaciar(engine)  # por si quedó algo de una corrida cortada
    yield engine
    _vaciar(engine)
    engine.dispose()


@pytest.fixture
def db(motor):
    """Una sesión sobre la base de prueba, con las tablas de los modelos."""
    Base.metadata.create_all(motor)
    with sessionmaker(bind=motor)() as sesion:
        yield sesion


@pytest.fixture
def servidor(monkeypatch, motor):
    """El servidor web con una base de prueba y sin mandar nada a WhatsApp.

    Devuelve la lista de mensajes que el bot habría enviado: (teléfono, texto).
    """
    from app.api import webhook
    from app.canales import whatsapp
    from app.infra import db

    Base.metadata.create_all(motor)
    monkeypatch.setattr(webhook, "SessionLocal", sessionmaker(bind=motor, expire_on_commit=False))
    monkeypatch.setattr(db, "preparar_base", lambda: None)
    enviados: list[tuple[str, str]] = []
    monkeypatch.setattr(whatsapp, "enviar_texto", lambda tel, txt: enviados.append((tel, txt)))
    return enviados
