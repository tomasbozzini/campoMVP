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
python -m app auditoria [--limite 50]            últimas acciones sensibles (solo ids)
python -m app eval [--funcion ayuda] [--desde 1] [--limite 10] [--esfuerzo low] [--tope-usd 0.5]
                                                 set de evaluación contra la IA real
"""

import argparse
import csv
import io
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app import modulos
from app.fuentes import precios as fuentes_precios
from app.fuentes import senasa as fuentes_senasa
from app.ia import evaluacion, proveedor
from app.infra import migrar
from app.infra.config import config
from app.infra.db import SessionLocal, engine
from app.infra.logs import configurar_logs
from app.modulos.comun import precios, senasa
from app.nucleo import auditoria, pipeline, usuarios

TELEFONO_CHAT = "5490000000000"
CARPETA_CHAT = Path("archivos_chat")  # los PDF y planillas que manda el bot en el chat de prueba


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
            respuesta = pipeline.atender(db, telefono, texto)
            db.commit()
        print(f"\nbot> {respuesta.texto}\n")
        for adjunto in respuesta.adjuntos:
            # En WhatsApp llega como documento; acá queda en una carpeta (fuera del repo, ver .gitignore).
            CARPETA_CHAT.mkdir(exist_ok=True)
            destino = CARPETA_CHAT / adjunto.nombre
            destino.write_bytes(adjunto.contenido)
            print(f"bot> 📎 {destino}\n")


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


def _auditoria(db: Session, args: argparse.Namespace) -> None:
    filas = auditoria.ultimas(db, args.limite)
    if not filas:
        print("Todavía no hay acciones registradas.")
    for f in reversed(filas):
        fecha = f.fecha.astimezone(config.zona_horaria) if f.fecha.tzinfo else f.fecha
        actor = f"#{f.actor}" if f.actor is not None else "terminal"
        sobre = f"#{f.sobre}" if f.sobre is not None else "-"
        detalle = " ".join(f"{clave}={valor}" for clave, valor in (f.detalle or {}).items())
        print(f"{fecha:%Y-%m-%d %H:%M}  {f.accion:<18} por {actor:<9} sobre {sobre:<6} {detalle}".rstrip())


def _eval(args: argparse.Namespace) -> None:
    """El set de evaluación contra la IA real, sin respaldo: mide un solo proveedor."""
    nombre = args.proveedor or ("openrouter" if config.openrouter_api_key else "groq")
    if nombre == "openrouter" and not config.openrouter_api_key:
        sys.exit("Falta OPENROUTER_API_KEY en el .env")
    if nombre == "groq" and not config.groq_api_key:
        sys.exit("Falta GROQ_API_KEY en el .env")
    frases = evaluacion.elegir(evaluacion.cargar(), args.funcion or (), args.desde, args.limite)
    if not frases:
        sys.exit("No hay frases con esos filtros.")
    esfuerzo = args.esfuerzo or config.openrouter_esfuerzo
    detalle = f"esfuerzo {esfuerzo}" if nombre == "openrouter" else config.groq_modelo
    print(f"{len(frases)} frases contra {nombre} ({detalle}), rubro {args.rubro}, tope USD {args.tope_usd:.2f}\n")
    logging.getLogger("app.ia.proveedor").setLevel(logging.WARNING)  # cada llamada se muestra abajo

    def mostrar(r: evaluacion.Resultado) -> None:
        marca = "✓" if r.bien else "✗"
        tokens = sum(u.tokens_entrada + u.tokens_salida for u in r.usos)
        linea = f"{marca} {r.segundos:5.1f} s {tokens:6} tok  {r.frase.funcion:<18} {r.frase.frase}"
        if r.error:
            linea += f"\n      error: {r.error}"
        elif not r.bien:
            linea += f"\n      esperaba {list(r.frase.intenciones)} y vino {list(r.obtenidas)}"
        print(linea, flush=True)

    partes = modulos.partes(modulos.del_rubro(args.rubro))
    resultados, frenado = evaluacion.correr(
        frases, proveedor.uno_solo(nombre, esfuerzo), partes, _hoy(), args.tope_usd, args.pausa, mostrar
    )
    r = evaluacion.resumir(resultados)
    costo = f"USD {r.costo_usd:.4f}" if r.costo_usd is not None else "sin dato (el proveedor no lo informa)"
    print(
        f"\nPrecisión: {r.bien}/{r.total} ({r.precision:.0%})"
        f"\nLlamadas: {r.total} ({r.errores} con error)"
        f"\nTokens: {r.tokens_entrada} de entrada, {r.tokens_salida} de salida ({r.tokens_razonamiento} de razonamiento)"
        f"\nCosto: {costo}"
        f"\nDemora: mediana {r.mediana:.1f} s, p95 {r.p95:.1f} s"
    )
    if frenado:
        print(f"\n⚠️ Frené en {r.total} de {len(frases)} frases: se llegó al tope de USD {args.tope_usd:.2f}.")


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
    parser = argparse.ArgumentParser(prog="python -m app", description="CampoBot")
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

    registro_acciones = comandos.add_parser("auditoria", help="últimas acciones sensibles (solo ids)")
    registro_acciones.add_argument("--limite", type=int, default=50, help="cuántas mostrar (50 por defecto)")
    registro_acciones.set_defaults(ejecutar=_auditoria)

    evaluar = comandos.add_parser("eval", help="set de evaluación contra la IA real (cuesta plata)")
    evaluar.add_argument("--funcion", action="append", help="solo las frases de esa función (se puede repetir)")
    evaluar.add_argument("--desde", type=int, default=1, help="desde qué frase, contando desde 1")
    evaluar.add_argument("--limite", type=int, help="cuántas frases como mucho")
    evaluar.add_argument("--proveedor", choices=["openrouter", "groq"], help="por defecto, el principal")
    evaluar.add_argument("--esfuerzo", choices=["low", "medium", "high"], help="razonamiento (solo OpenRouter)")
    evaluar.add_argument("--rubro", choices=list(modulos.MODULOS_POR_RUBRO), default="productor")
    evaluar.add_argument("--tope-usd", type=float, default=0.50, help="frena al llegar a este costo (0.50)")
    evaluar.add_argument("--pausa", type=float, default=0.0, help="segundos entre llamadas (Groq gratis: 60)")

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
    if args.comando == "eval":  # no usa la base
        _eval(args)
        return
    # Solo `db migrar` cambia la base: el resto avisa si falta migrar.
    try:
        migrar.revisar(engine)
    except migrar.FaltaMigrar as e:
        sys.exit(str(e))
    with SessionLocal() as db:
        args.ejecutar(db, args)
