"""Dar y sacar acceso al bot desde la terminal (o desde Railway).

    python -m app.usuarios autorizar 5492494123456
    python -m app.usuarios quitar 5492494123456
    python -m app.usuarios lista

Los administradores (ADMIN_TELEFONOS) también pueden hacerlo por WhatsApp con
"autorizar <número>", "quitar <número>" y "autorizados".
"""

import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.modelos import Usuario


def autorizar(db: Session, telefono: str) -> Usuario:
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    if usuario is None:
        usuario = Usuario(telefono=telefono)
        db.add(usuario)
    usuario.autorizado = True
    db.flush()
    return usuario


def quitar(db: Session, telefono: str) -> bool:
    """Saca el acceso. Los registros de la persona se conservan."""
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    if usuario is None or not usuario.autorizado:
        return False
    usuario.autorizado = False
    db.flush()
    return True


def autorizados(db: Session) -> list[Usuario]:
    return list(db.scalars(select(Usuario).where(Usuario.autorizado.is_(True)).order_by(Usuario.creado)).all())


def main() -> None:
    from app.bot import normalizar_telefono
    from app.infra.db import SessionLocal, crear_tablas

    comando = sys.argv[1] if len(sys.argv) > 1 else ""
    crear_tablas()
    with SessionLocal() as db:
        if comando == "lista":
            for u in autorizados(db):
                print(u.telefono, u.nombre or "")
            return
        if comando in ("autorizar", "quitar") and len(sys.argv) > 2:
            telefono = normalizar_telefono(" ".join(sys.argv[2:]))
            if telefono is None:
                sys.exit("Número inválido. Usá el formato internacional, ej: 5492494123456")
            if comando == "autorizar":
                autorizar(db, telefono)
                print(f"{telefono} autorizado")
            else:
                print(f"{telefono}: acceso quitado" if quitar(db, telefono) else f"{telefono} no tenía acceso")
            db.commit()
            return
        print("Uso: python -m app.usuarios autorizar <número> | quitar <número> | lista")


if __name__ == "__main__":
    main()
