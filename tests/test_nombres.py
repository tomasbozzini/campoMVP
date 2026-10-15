"""Convención de nombres de los constraints: la misma que usa Postgres por defecto.

Así las bases de Postgres que ya existen (creadas antes de la convención, por la 0001 o por
create_all) ya tienen los nombres que espera el código, y una migración futura puede
referirse a un constraint por su nombre sin depender de cómo se creó la base.
"""

from sqlalchemy import Engine, create_engine, inspect, text

from app.infra import migrar
from app.infra.db import Base

NOMBRES = {
    "cuentas": {"pk": "cuentas_pkey", "fk": set(), "uq": set()},
    "usuarios": {"pk": "usuarios_pkey", "fk": {"usuarios_cuenta_id_fkey"}, "uq": set()},
    "eventos": {"pk": "eventos_pkey", "fk": {"eventos_cuenta_id_fkey", "eventos_usuario_id_fkey"}, "uq": set()},
    "mensajes_procesados": {"pk": "mensajes_procesados_pkey", "fk": set(), "uq": set()},
    "cotizaciones": {"pk": "cotizaciones_pkey", "fk": set(), "uq": {"cotizaciones_fuente_producto_plaza_fecha_key"}},
    "uso_diario": {
        "pk": "uso_diario_pkey",
        "fk": {"uso_diario_usuario_id_fkey"},
        "uq": {"uso_diario_usuario_id_fecha_key"},
    },
    "productos_veterinarios": {"pk": "productos_veterinarios_pkey", "fk": set(), "uq": set()},
    "mensajes_chat": {"pk": "mensajes_chat_pkey", "fk": {"mensajes_chat_usuario_id_fkey"}, "uq": set()},
    "borrados_pendientes": {
        "pk": "borrados_pendientes_pkey",
        "fk": {"borrados_pendientes_usuario_id_fkey"},
        "uq": set(),
    },
}


def _nombres(engine: Engine) -> dict[str, dict[str, object]]:
    i = inspect(engine)
    return {
        tabla: {
            "pk": i.get_pk_constraint(tabla)["name"],
            "fk": {f["name"] for f in i.get_foreign_keys(tabla)},
            "uq": {u["name"] for u in i.get_unique_constraints(tabla)},
        }
        for tabla in i.get_table_names()
        if tabla != "alembic_version"
    }


def test_los_modelos_nombran_los_constraints_como_postgres(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/modelos.db")  # SQLite guarda los nombres que le dan
    Base.metadata.create_all(engine)
    assert _nombres(engine) == NOMBRES


def test_una_base_creada_sin_nombres_queda_con_los_de_la_convencion(motor):
    """La 0001 crea los constraints sin nombre: Postgres los nombra solo (y la 0002 no hace
    nada) y en SQLite los nombra la 0002. En el CI corre también sobre Postgres."""
    with motor.begin() as conexion:
        migrar.esquema_base().create_all(conexion)  # como antes de la convención
    if motor.dialect.name == "postgresql":
        assert _nombres(motor) == NOMBRES  # Postgres ya los tenía antes de migrar

    migrar.preparar_base(motor)
    assert _nombres(motor) == NOMBRES
    with motor.connect() as conexion:
        assert migrar.diferencias(conexion) == []


def test_la_0002_no_pierde_datos(motor):
    """En SQLite recrea las tablas: los datos tienen que quedar iguales."""
    with motor.begin() as conexion:
        migrar.esquema_base().create_all(conexion)
        conexion.execute(
            text(
                "insert into usuarios (id, telefono, autorizado, creado) values (1, '5491100000001', true, '2026-10-01')"
            )
        )
        conexion.execute(text(
            "insert into eventos (usuario_id, categoria, tipo, valor, fecha_evento, creado, extra) "
            "values (1, 'campo', 'lluvia', 20, '2026-10-01', '2026-10-01', '{\"mm\": 20}')"
        ))  # fmt: skip
        conexion.execute(text("insert into uso_diario (usuario_id, fecha, cantidad) values (1, '2026-10-01', 3)"))

    migrar.preparar_base(motor)

    with motor.connect() as conexion:
        assert conexion.execute(text("select telefono from usuarios")).scalars().all() == ["5491100000001"]
        assert conexion.execute(text("select tipo, valor from eventos")).all() == [("lluvia", 20)]
        assert conexion.execute(text("select cantidad from uso_diario")).scalars().all() == [3]
