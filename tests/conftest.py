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

    from app.api import webhook
    from app.infra import db

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(webhook, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(db, "crear_tablas", lambda: None)
    enviados: list[tuple[str, str]] = []
    monkeypatch.setattr(webhook.whatsapp, "enviar_texto", lambda tel, txt: enviados.append((tel, txt)))
    return enviados
