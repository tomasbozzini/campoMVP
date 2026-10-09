"""Probar el bot desde la terminal, sin WhatsApp:  python -m app.cli [telefono]"""

import sys

from app import bot
from app.db import SessionLocal, crear_tablas


def main() -> None:
    telefono = sys.argv[1] if len(sys.argv) > 1 else "5490000000000"
    crear_tablas()
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
