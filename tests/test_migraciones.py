"""Migraciones: crean la base desde cero y adoptan una base vieja sin perder datos."""

import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Column, MetaData, String, inspect, text
from sqlalchemy.orm import sessionmaker

from app.infra import migrar
from app.infra.db import Base
from app.infra.modelos import Evento, Usuario

RAIZ = Path(__file__).parent.parent
ULTIMA = ScriptDirectory(str(migrar.CARPETA)).get_current_head() or ""


@pytest.fixture
def engine(motor):
    return motor


def _version_y_diferencias(engine):
    with engine.connect() as c:
        return migrar.version(c), migrar.diferencias(c)


def test_base_vacia_queda_igual_que_los_modelos(engine):
    migrar.preparar_base(engine)
    assert _version_y_diferencias(engine) == (ULTIMA, [])


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

    assert _version_y_diferencias(engine) == (ULTIMA, [])
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


def _base_vieja_con_datos(engine, sin: tuple[str, ...] = ()):
    """Una base como la creaba el código antes de Alembic (create_all), con un usuario y un registro."""
    Base.metadata.create_all(engine, tables=[t for n, t in Base.metadata.tables.items() if n not in sin])
    with sessionmaker(bind=engine)() as db:
        u = Usuario(telefono="5491100000001", autorizado=True)
        db.add(u)
        db.flush()
        db.add(Evento(usuario_id=u.id, categoria="campo", tipo="lluvia", valor=20, fecha_evento=date(2026, 10, 1)))
        db.commit()


MIGRACION_NUEVA = '''"""Prueba: una migración posterior a la base, que agrega una columna."""

import sqlalchemy as sa
from alembic import op

revision = "0099"
down_revision = "ULTIMA"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("usuarios") as tabla:
        tabla.add_column(sa.Column("nota", sa.String(50), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("usuarios") as tabla:
        tabla.drop_column("nota")
'''


def test_base_vieja_igual_a_la_0001_se_adopta_aunque_haya_migraciones_nuevas(engine, tmp_path, monkeypatch):
    """El código ya va por una migración más (modelos con una columna nueva) y la base es de antes de Alembic."""
    _base_vieja_con_datos(engine)
    carpeta = tmp_path / "migraciones"
    shutil.copytree(migrar.CARPETA, carpeta, ignore=shutil.ignore_patterns("__pycache__"))
    (carpeta / "versions" / "0099_nota.py").write_text(MIGRACION_NUEVA.replace("ULTIMA", ULTIMA), encoding="utf-8")
    monkeypatch.setattr(migrar, "CARPETA", carpeta)
    modelos_nuevos = MetaData()
    for tabla in Base.metadata.tables.values():
        tabla.to_metadata(modelos_nuevos)
    modelos_nuevos.tables["usuarios"].append_column(Column("nota", String(50)))
    monkeypatch.setattr(Base, "metadata", modelos_nuevos)

    migrar.preparar_base(engine)

    assert _version_y_diferencias(engine) == ("0099", [])
    with engine.connect() as c:
        assert c.execute(text("select telefono, nota from usuarios")).all() == [("5491100000001", None)]
        assert c.execute(text("select valor from eventos")).scalars().all() == [20]


def test_base_vieja_a_la_que_le_faltan_tablas_enteras_se_completa(engine):
    """Bases de antes de que existieran el historial de charla y los borrados con confirmación."""
    _base_vieja_con_datos(engine, sin=("mensajes_chat", "borrados_pendientes"))

    migrar.preparar_base(engine)

    assert _version_y_diferencias(engine) == (ULTIMA, [])
    with engine.connect() as c:
        assert c.execute(text("select valor from eventos")).scalars().all() == [20]


def test_una_migracion_generada_pasa_ruff(engine, tmp_path, monkeypatch):
    """`alembic revision --autogenerate` escribe con comillas simples y sin ordenar: los hooks
    de alembic.ini la formatean para que pase el CI."""
    migrar.preparar_base(engine)
    carpeta = tmp_path / "migraciones"
    shutil.copytree(migrar.CARPETA, carpeta, ignore=shutil.ignore_patterns("__pycache__"))
    modelos_nuevos = MetaData()
    for tabla in Base.metadata.tables.values():
        tabla.to_metadata(modelos_nuevos)
    modelos_nuevos.tables["usuarios"].append_column(Column("nota", String(50)))
    monkeypatch.setattr(Base, "metadata", modelos_nuevos)

    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("script_location", str(carpeta))
    with engine.connect() as conexion:
        config.attributes["conexion"] = conexion
        command.revision(config, message="agrega nota", autogenerate=True, rev_id="0099")

    generada = next((carpeta / "versions").glob("0099_*.py"))
    assert "nota" in generada.read_text(encoding="utf-8")
    reglas = ["--no-cache", "--config", str(RAIZ / "pyproject.toml")]
    for chequeo in (["check", *reglas], ["format", "--check", *reglas]):
        resultado = subprocess.run(
            [sys.executable, "-m", "ruff", *chequeo, str(generada)], cwd=RAIZ, capture_output=True, text=True
        )
        assert resultado.returncode == 0, resultado.stdout + resultado.stderr
