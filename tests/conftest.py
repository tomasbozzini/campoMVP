import pytest

from app.infra.config import Configuracion, config


@pytest.fixture(autouse=True)
def configuracion_de_prueba(monkeypatch):
    """Los tests no leen el .env de la compu: parten de los valores por defecto, en desarrollo."""
    limpia = Configuracion(_env_file=None, entorno="desarrollo")
    for campo in Configuracion.model_fields:
        monkeypatch.setattr(config, campo, getattr(limpia, campo))


@pytest.fixture
def servidor(monkeypatch, tmp_path):
    """El servidor web con una base de prueba y sin mandar nada a WhatsApp.

    Devuelve la lista de mensajes que el bot habría enviado: (teléfono, texto).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import main
    from app.infra.db import Base

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(main, "crear_tablas", lambda: None)
    enviados: list[tuple[str, str]] = []
    monkeypatch.setattr(main.whatsapp, "enviar_texto", lambda tel, txt: enviados.append((tel, txt)))
    return enviados
