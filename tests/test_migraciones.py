"""Migraciones: crean la base desde cero y adoptan una base vieja sin perder datos."""

import shutil
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, Column, Date, DateTime, MetaData, String, bindparam, inspect, text
from sqlalchemy.orm import sessionmaker

from app.infra import migrar
from app.infra.db import Base
from app.nucleo import usuarios

RAIZ = Path(__file__).parent.parent
ULTIMA = ScriptDirectory(str(migrar.CARPETA)).get_current_head() or ""


@pytest.fixture
def engine(motor):
    return motor


def migrar_hasta(engine, revision: str) -> None:
    """Deja la base en esa revisión, como estaba una base de producción antes de un cambio."""
    with engine.begin() as conexion:
        command.upgrade(migrar._config(conexion), revision)


def _usuario_y_lluvia(engine) -> None:
    """Un usuario con un registro, cargados con SQL: sirve para cualquier versión del esquema."""
    # Con tipo, SQLAlchemy convierte los valores igual que en la base real (en SQLite, a texto).
    tipos = (bindparam("si", type_=Boolean), bindparam("ahora", type_=DateTime(timezone=True)))
    valores = {"si": True, "ahora": datetime(2026, 10, 1, tzinfo=UTC), "fecha": date(2026, 10, 1)}
    with engine.begin() as c:
        c.execute(
            text(
                "insert into usuarios (id, telefono, autorizado, creado) values (1, '5491100000001', :si, :ahora)"
            ).bindparams(*tipos),
            valores,
        )
        c.execute(
            text(
                "insert into eventos (id, usuario_id, categoria, tipo, valor, fecha_evento, creado) "
                "values (1, 1, 'campo', 'lluvia', 20, :fecha, :ahora)"
            ).bindparams(*tipos[1:], bindparam("fecha", type_=Date)),
            valores,
        )


def _version_y_diferencias(engine):
    with engine.connect() as c:
        return migrar.version(c), migrar.diferencias(c)


def test_base_vacia_queda_igual_que_los_modelos(engine):
    migrar.preparar_base(engine)
    assert _version_y_diferencias(engine) == (ULTIMA, [])


def test_base_de_antes_de_alembic_se_adopta_sin_perder_datos(engine):
    _base_vieja_con_datos(engine)

    migrar.preparar_base(engine)
    migrar.preparar_base(engine)  # correrlo de nuevo no cambia nada

    assert _version_y_diferencias(engine) == (ULTIMA, [])
    with engine.connect() as c:
        assert c.execute(text("select telefono from usuarios")).scalars().all() == ["5491100000001"]
        assert c.execute(text("select valor from eventos")).scalars().all() == [20]


def test_base_vieja_que_no_coincide_no_se_toca(engine):
    migrar.esquema_base().create_all(engine)
    with engine.begin() as c:
        # Una base de antes de la columna mensaje_id.
        c.execute(text("drop index ix_eventos_mensaje_id"))
        c.execute(text("alter table eventos drop column mensaje_id"))

    with pytest.raises(migrar.EsquemaDistinto, match="mensaje_id"):
        migrar.preparar_base(engine)
    assert "alembic_version" not in inspect(engine).get_table_names()


def _base_vieja_con_datos(engine, sin: tuple[str, ...] = ()):
    """Una base como la creaba el código antes de Alembic (create_all), con un usuario y un registro.

    Se arma con el esquema de la 0001 y no con los modelos actuales, que ya van varias
    migraciones más adelante: así eran las bases de antes de Alembic."""
    esquema = migrar.esquema_base()
    esquema.create_all(engine, tables=[t for n, t in esquema.tables.items() if n not in sin])
    _usuario_y_lluvia(engine)


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


def test_una_base_con_datos_en_cada_version_llega_a_la_ultima(engine):
    """Una base de producción en la 0002, con datos, se pone al día sin perderlos."""
    migrar_hasta(engine, "0002")
    _usuario_y_lluvia(engine)

    migrar.preparar_base(engine)

    assert _version_y_diferencias(engine) == (ULTIMA, [])
    with engine.connect() as c:
        assert c.execute(text("select telefono from usuarios")).scalars().all() == ["5491100000001"]
        assert c.execute(text("select valor from eventos")).scalars().all() == [20]


def test_0003_cada_usuario_existente_recibe_su_cuenta_con_sus_registros(engine):
    migrar_hasta(engine, "0002")
    _usuario_y_lluvia(engine)  # usuario 1 con un registro
    with engine.begin() as c:
        c.execute(
            text(
                "insert into usuarios (id, telefono, autorizado, creado) values (2, '5491100000002', :si, :ahora)"
            ).bindparams(bindparam("si", type_=Boolean), bindparam("ahora", type_=DateTime(timezone=True))),
            {"si": True, "ahora": datetime(2026, 10, 2, tzinfo=UTC)},
        )
        c.execute(
            text(
                "insert into eventos (id, usuario_id, categoria, tipo, valor, fecha_evento, creado) "
                "values (2, 2, 'campo', 'lluvia', 7, :fecha, :ahora), (3, 2, 'campo', 'lluvia', 8, :fecha, :ahora)"
            ).bindparams(bindparam("fecha", type_=Date), bindparam("ahora", type_=DateTime(timezone=True))),
            {"fecha": date(2026, 10, 2), "ahora": datetime(2026, 10, 2, tzinfo=UTC)},
        )
        c.execute(
            text(
                "insert into usuarios (id, telefono, autorizado, creado) values (3, '5491100000003', :no, :ahora)"
            ).bindparams(bindparam("no", type_=Boolean), bindparam("ahora", type_=DateTime(timezone=True))),
            {"no": False, "ahora": datetime(2026, 10, 3, tzinfo=UTC)},
        )

    migrar.preparar_base(engine)

    assert _version_y_diferencias(engine) == (ULTIMA, [])
    with engine.connect() as c:
        cuentas = dict(c.execute(text("select id, cuenta_id from usuarios")).all())
        eventos = c.execute(text("select usuario_id, cuenta_id, valor from eventos order by id")).all()
        assert c.execute(text("select count(*) from cuentas")).scalar_one() == 3
    assert len(set(cuentas.values())) == 3  # una cuenta distinta por usuario
    assert eventos == [(1, cuentas[1], 20), (2, cuentas[2], 7), (2, cuentas[2], 8)]

    # Las altas que siguen no chocan con las cuentas que creó la migración.
    with sessionmaker(bind=engine)() as db:
        nuevo = usuarios.nuevo(db, "5491100000004")
        db.commit()
        assert nuevo.cuenta_id not in cuentas.values()


def test_0003_no_adivina_de_quien_son_registros_sin_usuario(engine):
    """SQLite no controla las claves foráneas: una base vieja puede tener registros huérfanos."""
    migrar_hasta(engine, "0002")
    _usuario_y_lluvia(engine)
    if engine.dialect.name == "postgresql":
        pytest.skip("Postgres no deja guardar registros sin usuario")
    with engine.begin() as c:
        c.execute(text("update eventos set usuario_id = 99"))

    with pytest.raises(RuntimeError, match="1 registros de usuarios que ya no existen"):
        migrar.preparar_base(engine)
    with engine.connect() as c:
        assert migrar.version(c) == "0002"
        assert c.execute(text("select usuario_id, valor from eventos")).all() == [(99, 20)]
    assert "cuentas" not in inspect(engine).get_table_names()  # "no se cambió nada"
