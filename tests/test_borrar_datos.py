"""Derecho de supresión: "borrar mis datos" no deja nada de la persona en ninguna tabla.

El test recorre todas las tablas de los modelos con `usuario_id` o `cuenta_id`, así una
tabla nueva queda cubierta sola. Para que no pase "de vacío", antes de borrar exige que la
persona tenga al menos una fila en cada una de esas tablas: si se agrega una tabla, hay que
sumar sus datos en `_todo_lo_de`.
"""

from datetime import UTC, date, datetime

from sqlalchemy import Table, func, select

from app.infra.db import Base
from app.infra.modelos import BorradoPendiente, Cuenta, Evento, MensajeChat, UsoDiario, Usuario
from app.nucleo import pipeline, usuarios

HOY = date(2026, 10, 15)


def _todo_lo_de(db, u: Usuario) -> None:
    """Una fila de la persona en cada tabla que guarda algo suyo."""
    db.add_all(
        [
            Evento(cuenta_id=u.cuenta_id, usuario_id=u.id, categoria="campo", tipo="lluvia", fecha_evento=HOY),
            MensajeChat(usuario_id=u.id, rol="usuario", texto="hola"),
            UsoDiario(usuario_id=u.id, fecha=HOY, cantidad=1),
            BorradoPendiente(usuario_id=u.id, ids=[1], creado=datetime.now(UTC)),
        ]
    )
    db.flush()


def _tablas_con_duenio() -> list[tuple[Table, str]]:
    return [
        (tabla, columna)
        for tabla in Base.metadata.tables.values()
        for columna in ("usuario_id", "cuenta_id")
        if columna in tabla.c
    ]


def _filas(db, u: Usuario) -> dict[str, int]:
    valores = {"usuario_id": u.id, "cuenta_id": u.cuenta_id}
    return {
        f"{tabla.name}.{columna}": db.scalar(
            select(func.count()).select_from(tabla).where(tabla.c[columna] == valores[columna])
        )
        for tabla, columna in _tablas_con_duenio()
    }


def test_borrar_mis_datos_no_deja_nada_en_ninguna_tabla(db):
    u = usuarios.autorizar(db, "5491100000001")
    otro = usuarios.autorizar(db, "5491100000002")
    _todo_lo_de(db, u)
    _todo_lo_de(db, otro)
    sin_datos = [tabla for tabla, n in _filas(db, u).items() if n == 0]
    assert sin_datos == [], "Sumá datos de estas tablas en _todo_lo_de"

    pipeline.manejar_mensaje(db, u.telefono, "borrar mis datos", hoy=HOY)
    pipeline.manejar_mensaje(db, u.telefono, "confirmo borrar mis datos", hoy=HOY)

    assert all(n == 0 for n in _filas(db, u).values()), _filas(db, u)
    assert db.get(Usuario, u.id) is None
    assert db.get(Cuenta, u.cuenta_id) is None
    assert all(n > 0 for n in _filas(db, otro).values())  # lo del otro, intacto
