"""Comandos de terminal:  python -m app <comando>

python -m app chat [telefono]                    chat con el bot, sin WhatsApp
python -m app usuarios autorizar 5492494123456   da acceso a un número
python -m app usuarios quitar 5492494123456      le saca el acceso
python -m app usuarios lista                     números con acceso
python -m app precios actualizar                 descarga las fuentes oficiales de precios
python -m app precios cargar precios.csv         carga precios a mano
python -m app precios ver soja                   muestra lo que respondería el bot
python -m app senasa actualizar                  descarga el registro de SENASA
python -m app senasa cargar registro.csv --fecha 2026-10-10 --url https://...
python -m app senasa ver ivermectina
python -m app db migrar                          crea la base o la pone al día (sin perder datos)
python -m app db estado                          versión de la base y diferencias con el código
"""

import argparse
import csv
import io
import sys
from datetime import date, datetime

from sqlalchemy.orm import Session

from app import modulos
from app.fuentes import precios as fuentes_precios
from app.fuentes import senasa as fuentes_senasa
from app.infra import migrar
from app.infra.config import config
from app.infra.db import SessionLocal, engine, preparar_base
from app.infra.logs import configurar_logs
from app.modulos.comun import precios, senasa
from app.nucleo import pipeline, usuarios

TELEFONO_CHAT = "5490000000000"


def _hoy() -> date:
    return datetime.now(config.zona_horaria).date()


def _chat(_db: Session, args: argparse.Namespace) -> None:
    """El número con el que chateás se autoriza solo, porque es una prueba local."""
    telefono = args.telefono
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
            respuesta = pipeline.manejar_mensaje(db, telefono, texto)
            db.commit()
        print(f"\nbot> {respuesta}\n")


def _usuarios(db: Session, args: argparse.Namespace) -> None:
    if args.accion == "lista":
        for u in usuarios.autorizados(db):
            print(u.telefono, u.nombre or "")
        return
    telefono = usuarios.normalizar_telefono(" ".join(args.telefono))
    if telefono is None:
        sys.exit("Número inválido. Usá el formato internacional, ej: 5492494123456")
    if args.accion == "autorizar":
        usuarios.autorizar(db, telefono)
        print(f"{telefono} autorizado")
    else:
        print(f"{telefono}: acceso quitado" if usuarios.quitar(db, telefono) else f"{telefono} no tenía acceso")
    db.commit()


def _precios(db: Session, args: argparse.Namespace) -> None:
    if args.accion == "actualizar":
        fuentes_precios.actualizar(db)
    elif args.accion == "cargar":
        for fuente, cantidad in fuentes_precios.cargar_csv(db, args.csv).items():
            print(f"{fuente}: {cantidad} precios")
        db.commit()
    else:
        print(precios.responder(db, args.producto, None, _hoy()))


def _senasa(db: Session, args: argparse.Namespace) -> None:
    if args.accion == "actualizar":
        fecha = date.fromisoformat(args.fecha) if args.fecha else _hoy()
        n = fuentes_senasa.actualizar(db, fecha, args.url)
        db.commit()
        print(f"{n} productos cargados (datos al {fecha.strftime('%d/%m/%Y')})")
    elif args.accion == "cargar":
        with open(args.csv, encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        n = fuentes_senasa.reemplazar_registro(db, filas, date.fromisoformat(args.fecha), args.url)
        db.commit()
        print(f"{n} productos cargados")
    else:
        print(senasa.responder(db, args.texto))


def _db(args: argparse.Namespace) -> None:
    if args.accion == "migrar":
        try:
            migrar.preparar_base(engine)
        except migrar.EsquemaDistinto as e:
            sys.exit(str(e))
    with engine.connect() as conexion:
        print(f"Versión de la base: {migrar.version(conexion) or 'sin Alembic'}")
        difieren = migrar.diferencias(conexion)
    print("Coincide con el código." if not difieren else "Difiere del código:\n  " + "\n  ".join(difieren))


def _argumentos() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app", description="Asistente de campo")
    comandos = parser.add_subparsers(dest="comando", required=True)

    chat = comandos.add_parser("chat", help="chatear con el bot desde la terminal")
    chat.add_argument("telefono", nargs="?", default=TELEFONO_CHAT)
    chat.set_defaults(ejecutar=_chat)

    gente = comandos.add_parser("usuarios", help="dar y sacar acceso")
    acciones = gente.add_subparsers(dest="accion", required=True)
    for accion in ("autorizar", "quitar"):
        p = acciones.add_parser(accion)
        p.add_argument("telefono", nargs="+", help="ej: 5492494123456 o +54 9 249 412-3456")
    acciones.add_parser("lista")
    gente.set_defaults(ejecutar=_usuarios)

    cotizaciones = comandos.add_parser("precios", help="precios de fuentes oficiales")
    acciones = cotizaciones.add_subparsers(dest="accion", required=True)
    acciones.add_parser("actualizar", help="descarga todas las fuentes registradas")
    acciones.add_parser("cargar", help="carga un CSV").add_argument("csv")
    acciones.add_parser("ver", help="lo que respondería el bot").add_argument("producto", nargs="?")
    cotizaciones.set_defaults(ejecutar=_precios)

    registro = comandos.add_parser("senasa", help="registro de productos veterinarios")
    acciones = registro.add_subparsers(dest="accion", required=True)
    traer = acciones.add_parser("actualizar", help="descarga la consulta pública de SENASA")
    traer.add_argument("--fecha", help="fecha de los datos; por defecto, la de hoy")
    traer.add_argument("--url", default=fuentes_senasa.URL_OFICIAL, help="página oficial que se guarda como fuente")
    cargar = acciones.add_parser("cargar", help="reemplaza el registro con un CSV")
    cargar.add_argument("csv")
    cargar.add_argument("--fecha", required=True, help="fecha de los datos según SENASA, YYYY-MM-DD")
    cargar.add_argument("--url", required=True, help="página oficial de SENASA de donde salen los datos")
    acciones.add_parser("ver", help="lo que respondería el bot").add_argument("texto")
    registro.set_defaults(ejecutar=_senasa)

    base = comandos.add_parser("db", help="base de datos y migraciones")
    acciones = base.add_subparsers(dest="accion", required=True)
    acciones.add_parser("migrar", help="crea la base o aplica las migraciones que falten")
    acciones.add_parser("estado", help="versión de la base y diferencias con el código")

    return parser


def main(argv: list[str] | None = None) -> None:
    args = _argumentos().parse_args(argv)
    # La consola de Windows usa cp1252 y se rompe con los emojis de las respuestas.
    for flujo in (sys.stdout, sys.stderr, sys.stdin):
        if isinstance(flujo, io.TextIOWrapper):
            flujo.reconfigure(encoding="utf-8")
    configurar_logs()
    modulos.cargar()
    if args.comando == "db":
        _db(args)
        return
    preparar_base()
    with SessionLocal() as db:
        args.ejecutar(db, args)
