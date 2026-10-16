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
from sqlalchemy import JSON, Boolean, Column, Date, DateTime, MetaData, String, bindparam, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.infra import migrar
from app.infra.db import Base
from app.infra.modelos import Usuario
from app.nucleo import usuarios
from app.nucleo.cuaderno import Cuaderno

RAIZ = Path(__file__).parent.parent
ULTIMA = ScriptDirectory(str(migrar.CARPETA)).get_current_head() or ""


@pytest.fixture
def engine(motor):
    return motor


def migrar_hasta(engine, revision: str) -> None:
    """Deja la base en esa revisión, como estaba una base de producción antes de un cambio."""
    with engine.begin() as conexion:
        command.upgrade(migrar._config(conexion), revision)


def _insertar_usuario(c, telefono: str, autorizado: bool = True) -> int:
    """Un usuario cargado con SQL, sin id: la base lo numera con su secuencia, como en
    producción (en Postgres, un id puesto a mano no avanza la secuencia)."""
    return int(
        c.execute(
            text(
                "insert into usuarios (telefono, autorizado, creado) values (:telefono, :autorizado, :creado) returning id"
            ).bindparams(bindparam("autorizado", type_=Boolean), bindparam("creado", type_=DateTime(timezone=True))),
            {"telefono": telefono, "autorizado": autorizado, "creado": datetime(2026, 10, 1, tzinfo=UTC)},
        ).scalar_one()
    )


def _insertar_lluvia(c, usuario_id: int, valor: float) -> None:
    # Con tipo, SQLAlchemy convierte los valores igual que en la base real (en SQLite, a texto).
    c.execute(
        text(
            "insert into eventos (usuario_id, categoria, tipo, valor, fecha_evento, creado) "
            "values (:usuario_id, 'campo', 'lluvia', :valor, :fecha, :creado)"
        ).bindparams(bindparam("fecha", type_=Date), bindparam("creado", type_=DateTime(timezone=True))),
        {
            "usuario_id": usuario_id,
            "valor": valor,
            "fecha": date(2026, 10, 1),
            "creado": datetime(2026, 10, 1, tzinfo=UTC),
        },
    )


def _usuario_y_lluvia(engine) -> int:
    """Un usuario con un registro, cargados con SQL: sirve para cualquier versión del esquema."""
    with engine.begin() as c:
        usuario_id = _insertar_usuario(c, "5491100000001")
        _insertar_lluvia(c, usuario_id, 20)
    return usuario_id


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
    uno = _usuario_y_lluvia(engine)
    with engine.begin() as c:
        dos = _insertar_usuario(c, "5491100000002")
        _insertar_lluvia(c, dos, 7)
        _insertar_lluvia(c, dos, 8)
        _insertar_usuario(c, "5491100000003", autorizado=False)  # sin registros

    migrar.preparar_base(engine)

    assert _version_y_diferencias(engine) == (ULTIMA, [])
    with engine.connect() as c:
        cuentas = dict(c.execute(text("select id, cuenta_id from usuarios")).all())
        eventos = c.execute(text("select usuario_id, cuenta_id, valor from eventos order by id")).all()
        assert c.execute(text("select count(*) from cuentas")).scalar_one() == 3
    assert len(set(cuentas.values())) == 3  # una cuenta distinta por usuario
    assert eventos == [(uno, cuentas[uno], 20), (dos, cuentas[dos], 7), (dos, cuentas[dos], 8)]

    # Las altas que siguen no chocan con las cuentas que creó la migración.
    with sessionmaker(bind=engine)() as db:
        nuevo = usuarios.nuevo(db, "5491100000004")
        db.commit()
        assert nuevo.cuenta_id not in cuentas.values()


def _base_0006_con_campos(engine) -> tuple[int, int]:
    """Dos personas (cada una con su cuenta) con registros que nombran campos y lotes como
    texto, como quedaban antes de la 0007."""
    migrar_hasta(engine, "0006")
    with engine.begin() as c:
        cuentas = []
        creado = bindparam("creado", type_=DateTime(timezone=True))
        for telefono, actual in (("5491100000001", "Estancia La Pastora"), ("5491100000002", "El Ombú")):
            cuenta_id = c.execute(
                text("insert into cuentas (creado) values (:creado) returning id").bindparams(creado),
                {"creado": datetime(2026, 10, 1, tzinfo=UTC)},
            ).scalar_one()
            usuario_id = c.execute(
                text(
                    "insert into usuarios (telefono, autorizado, creado, cuenta_id, establecimiento_actual) "
                    "values (:telefono, true, :creado, :cuenta, :actual) returning id"
                ).bindparams(creado),
                {
                    "telefono": telefono,
                    "creado": datetime(2026, 10, 1, tzinfo=UTC),
                    "cuenta": cuenta_id,
                    "actual": actual,
                },
            ).scalar_one()
            cuentas.append((usuario_id, cuenta_id))
        (uno, cuenta_uno), (dos, cuenta_dos) = cuentas
        registros = [
            # (usuario, cuenta, establecimiento, clave, lote, lote_destino)
            (uno, cuenta_uno, "La Pastora", "la pastora", "3", None),
            (uno, cuenta_uno, "la pastora", "la pastora", "Lote 3", "5"),  # otra forma, mismo campo y lote
            (uno, cuenta_uno, None, None, "3", None),  # lote suelto
            (uno, cuenta_uno, None, None, None, None),
            (dos, cuenta_dos, "La Pastora", "la pastora", "3", None),  # el mismo nombre en otra cuenta
        ]
        for usuario_id, cuenta_id, nombre, clave, lote, destino in registros:
            c.execute(
                text(
                    "insert into eventos (usuario_id, cuenta_id, establecimiento, establecimiento_clave, lote, "
                    "lote_destino, categoria, tipo, fecha_evento, creado) values (:u, :c, :n, :k, :l, :d, "
                    "'sanidad', 'vacunacion', :fecha, :creado)"
                ).bindparams(bindparam("fecha", type_=Date), bindparam("creado", type_=DateTime(timezone=True))),
                {
                    "u": usuario_id,
                    "c": cuenta_id,
                    "n": nombre,
                    "k": clave,
                    "l": lote,
                    "d": destino,
                    "fecha": date(2026, 10, 1),
                    "creado": datetime(2026, 10, 1, tzinfo=UTC),
                },
            )
    return cuenta_uno, cuenta_dos


def test_0007_los_campos_y_lotes_de_texto_pasan_a_tablas(engine):
    cuenta_uno, cuenta_dos = _base_0006_con_campos(engine)

    migrar.preparar_base(engine)

    assert _version_y_diferencias(engine) == (ULTIMA, [])
    with engine.connect() as c:
        campos = c.execute(text("select id, cuenta_id, nombre, clave from establecimientos order by id")).all()
        lotes = c.execute(text("select id, cuenta_id, establecimiento_id, nombre from lotes order by id")).all()
        eventos = c.execute(text("select establecimiento_id, lote_id, lote_destino_id from eventos order by id")).all()
        actuales = c.execute(text("select establecimiento_actual_id from usuarios order by id")).scalars().all()
        assert "establecimiento" not in {col["name"] for col in inspect(c).get_columns("eventos")}
    # Un establecimiento por cuenta y clave, con el nombre del primer registro. El actual del
    # segundo usuario ("El Ombú") no estaba en ningún registro: se crea.
    pastora_uno, pastora_dos, ombu = campos
    assert pastora_uno[1:] == (cuenta_uno, "La Pastora", "la pastora")
    assert pastora_dos[1:] == (cuenta_dos, "La Pastora", "la pastora")
    assert ombu[1:] == (cuenta_dos, "El Ombú", "el ombu")
    lote3, lote5, suelto, lote3_dos = lotes
    assert lote3[1:] == (cuenta_uno, pastora_uno[0], "3")
    assert lote5[1:] == (cuenta_uno, pastora_uno[0], "5")  # el destino, en el campo del registro
    assert suelto[1:] == (cuenta_uno, None, "3")
    assert lote3_dos[1:] == (cuenta_dos, pastora_dos[0], "3")
    assert eventos == [
        (pastora_uno[0], lote3[0], None),
        (pastora_uno[0], lote3[0], lote5[0]),
        (None, suelto[0], None),
        (None, None, None),
        (pastora_dos[0], lote3_dos[0], None),
    ]
    assert actuales == [pastora_uno[0], ombu[0]]

    # Los que se crean después no chocan con los que creó la migración.
    with sessionmaker(bind=engine)() as db:
        usuario = db.scalars(select(Usuario).where(Usuario.cuenta_id == cuenta_uno)).one()
        cuaderno = Cuaderno(db, usuario)
        pastora, esperanza = cuaderno.establecimiento("estancia la pastora"), cuaderno.establecimiento("La Esperanza")
        assert pastora is not None and pastora.id == pastora_uno[0]
        assert esperanza is not None and esperanza.id not in {f[0] for f in campos}
        assert cuaderno.lote("7", esperanza) is not None
        db.commit()


def test_0007_vuelve_atras_sin_perder_los_nombres(engine):
    _base_0006_con_campos(engine)
    migrar.preparar_base(engine)

    with engine.begin() as c:
        command.downgrade(migrar._config(c), "0006")

    with engine.connect() as c:
        assert migrar.version(c) == "0006"
        assert c.execute(
            text("select establecimiento, establecimiento_clave, lote, lote_destino from eventos order by id")
        ).all() == [
            ("La Pastora", "la pastora", "3", None),
            ("La Pastora", "la pastora", "3", "5"),
            (None, None, "3", None),
            (None, None, None, None),
            ("La Pastora", "la pastora", "3", None),
        ]
        # Vuelve el nombre del establecimiento, no cómo lo había escrito ("Estancia La Pastora").
        assert c.execute(text("select establecimiento_actual from usuarios order by id")).scalars().all() == [
            "La Pastora",
            "El Ombú",
        ]
        assert "establecimientos" not in inspect(c).get_table_names()


def test_0008_los_nombres_de_los_campos_quedan_prolijos(engine):
    _base_0006_con_campos(engine)
    migrar_hasta(engine, "0007")
    with engine.begin() as c:
        c.execute(text("update establecimientos set nombre = 'estancia  LA PASTORA' where nombre = 'La Pastora'"))

    migrar.preparar_base(engine)

    with engine.connect() as c:
        nombres = c.execute(text("select nombre, clave from establecimientos order by id")).all()
    assert nombres == [
        ("Estancia la Pastora", "la pastora"),  # la clave no cambia
        ("Estancia la Pastora", "la pastora"),
        ("El Ombú", "el ombu"),
    ]


def test_0010_agrega_los_pendientes_y_vuelve_atras(engine):
    """Solo agrega la tabla: los datos de antes no se tocan (lo cubre la prueba de cada versión)."""
    migrar_hasta(engine, "0009")
    migrar.preparar_base(engine)
    with engine.begin() as c:
        assert "pendientes" in inspect(c).get_table_names()
        command.downgrade(migrar._config(c), "0009")

    with engine.connect() as c:
        assert migrar.version(c) == "0009"
        assert "pendientes" not in inspect(c).get_table_names()


def test_0011_un_borrado_esperando_confirmacion_queda_como_de_registros(engine):
    migrar_hasta(engine, "0010")
    with engine.begin() as c:
        creado = bindparam("creado", type_=DateTime(timezone=True))
        cuenta_id = c.execute(
            text("insert into cuentas (creado) values (:creado) returning id").bindparams(creado),
            {"creado": datetime(2026, 10, 1, tzinfo=UTC)},
        ).scalar_one()
        usuario_id = c.execute(
            text(
                "insert into usuarios (cuenta_id, telefono, autorizado, creado) "
                "values (:cuenta, '5491100000001', :si, :creado) returning id"
            ).bindparams(bindparam("si", type_=Boolean), creado),
            {"cuenta": cuenta_id, "si": True, "creado": datetime(2026, 10, 1, tzinfo=UTC)},
        ).scalar_one()
        c.execute(
            text("insert into borrados_pendientes (usuario_id, ids, creado) values (:u, :ids, :creado)").bindparams(
                bindparam("ids", type_=JSON), bindparam("creado", type_=DateTime(timezone=True))
            ),
            {"u": usuario_id, "ids": [1, 2, 3, 4], "creado": datetime(2026, 10, 16, tzinfo=UTC)},
        )

    migrar.preparar_base(engine)
    with engine.connect() as c:
        assert c.execute(text("select que from borrados_pendientes")).scalar_one() == "registros"

    with engine.begin() as c:
        command.downgrade(migrar._config(c), "0010")
    with engine.connect() as c:
        assert migrar.version(c) == "0010"
        assert "que" not in [col["name"] for col in inspect(c).get_columns("borrados_pendientes")]
        assert c.execute(text("select usuario_id from borrados_pendientes")).scalar_one() == usuario_id


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
