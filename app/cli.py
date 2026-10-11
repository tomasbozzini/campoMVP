"""Probar el bot desde la terminal, sin WhatsApp:  python -m app.cli [telefono]

El número con el que chateás se autoriza solo, porque es una prueba local.
"""

import sys

from app import bot, usuarios
from app.db import SessionLocal, crear_tablas


def main() -> None:
    # La consola de Windows usa cp1252 y se rompe con los emojis de las respuestas.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    telefono = sys.argv[1] if len(sys.argv) > 1 else "5490000000000"
    crear_tablas()
    with SessionLocal() as db:
        usuarios.autorizar(db, telefono)
        db.commit()
    print(f"Chateando como {telefono}. Ctrl+C para salir.\n")
    while True:
        try:
            texto = input("vos> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not texto:
            continue
        with SessionLocal() as db:
            respuesta = bot.manejar_mensaje(db, telefono, texto)
            db.commit()
        print(f"\nbot> {respuesta}\n")


if __name__ == "__main__":
    main()
