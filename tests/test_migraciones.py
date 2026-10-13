"""Migraciones: crean la base desde cero y adoptan una base vieja sin perder datos."""

from datetime import date

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.infra import migrar
from app.infra.db import Base
from app.infra.modelos import Evento, Usuario


@pytest.fixture
def engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path}/base.db")


def _version_y_diferencias(engine):
    with engine.connect() as c:
        return migrar.version(c), migrar.diferencias(c)


def test_base_vacia_queda_igual_que_los_modelos(engine):
    migrar.preparar_base(engine)
    assert _version_y_diferencias(engine) == ("0001", [])


def test_base_de_antes_de_alembic_se_adopta_sin_perder_datos(engine):
    Base.metadata.create_all(engine)  # como la creaba el código hasta ahora
    with sessionmaker(bind=engine)() as db:
        u = Usuario(telefono="5491100000001", autorizado=True)
        db.add(u)
        db.flush()
        db.add(Evento(usuario_id=u.id, categoria="campo", tipo="lluvia", valor=20, fecha_evento=date(2026, 10, 1)))
        db.commit()

    migrar.preparar_base(engine)
    migrar.preparar_base(engine)  # correrlo de nuevo no cambia nada

    assert _version_y_diferencias(engine) == ("0001", [])
    with engine.connect() as c:
        assert c.execute(text("select telefono from usuarios")).scalars().all() == ["5491100000001"]
        assert c.execute(text("select valor from eventos")).scalars().all() == [20]


def test_base_vieja_que_no_coincide_no_se_toca(engine):
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        # Una base de antes de la columna mensaje_id.
        c.execute(text("drop index ix_eventos_mensaje_id"))
        c.execute(text("alter table eventos drop column mensaje_id"))

    with pytest.raises(migrar.EsquemaDistinto, match="mensaje_id"):
        migrar.preparar_base(engine)
    assert "alembic_version" not in inspect(engine).get_table_names()
