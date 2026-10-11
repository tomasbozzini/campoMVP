"""Verificación de productos veterinarios en el registro oficial de SENASA.

El bot NO informa precios de medicamentos ni de instrumental, ni indicaciones de uso:
solo dice si un producto figura en el registro de SENASA, con su número de registro,
titular y estado, y de qué fecha son los datos.

Los datos se cargan en la tabla `productos_veterinarios`, reemplazando todo el registro
de una vez (es una foto del Vademécum de SENASA a una fecha):

    python -m app.senasa cargar registro.csv
    python -m app.senasa ver ivermectina

Columnas del CSV: nombre,registro,titular,principio_activo,estado
La fuente, la URL y la fecha de los datos se pasan en la línea de comandos:

    python -m app.senasa cargar registro.csv --fecha 2026-10-10 \\
        --url https://www.argentina.gob.ar/senasa/...

Para automatizarlo, se puede escribir una función que descargue el Vademécum y devuelva
las mismas filas, y llamar a `reemplazar_registro` desde un cron.
"""

import argparse
import csv
import logging
import unicodedata
from datetime import date
from urllib.parse import urlparse

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models import ProductoVeterinario
from app.precios import es_oficial

log = logging.getLogger(__name__)

FUENTE = "SENASA - Vademécum de Productos Veterinarios"
MAX_RESULTADOS = 5
AVISO = "_Solo verifica el registro en SENASA. No es una indicación de uso ni una recomendación._"


def normalizar(texto: str | None) -> str | None:
    if not texto:
        return None
    texto = unicodedata.normalize("NFKD", str(texto).strip().lower())
    return "".join(c for c in texto if not unicodedata.combining(c)) or None


def reemplazar_registro(db: Session, filas: list[dict], fecha_datos: date, url: str) -> int:
    host = (urlparse(url).hostname or "").lower()
    if not es_oficial(url) or not (host == "gob.ar" or host.endswith(".gob.ar")):
        raise ValueError(f"La URL {url} no es de un organismo oficial (.gob.ar)")
    productos = []
    for f in filas:
        nombre = (f.get("nombre") or "").strip()
        registro = (f.get("registro") or "").strip()
        if not nombre or not registro:
            log.warning("Fila descartada (sin nombre o registro): %s", f)
            continue
        principio = (f.get("principio_activo") or "").strip() or None
        productos.append(ProductoVeterinario(
            nombre=nombre[:200],
            nombre_busqueda=normalizar(nombre)[:200],
            registro=registro[:40],
            titular=((f.get("titular") or "").strip() or None),
            principio_activo=principio and principio[:300],
            principio_busqueda=normalizar(principio) and normalizar(principio)[:300],
            estado=((f.get("estado") or "").strip().lower() or None),
            fecha_datos=fecha_datos,
            fuente=FUENTE,
            url=url,
        ))
    if not productos:
        raise ValueError("El archivo no tiene productos válidos; no se toca el registro actual")
    db.execute(delete(ProductoVeterinario))
    db.add_all(productos)
    db.flush()
    return len(productos)


def buscar(db: Session, texto: str) -> list[ProductoVeterinario]:
    clave = normalizar(texto)
    if not clave or len(clave) < 3:
        return []
    patron = f"%{clave}%"
    q = select(ProductoVeterinario).where(
        or_(
            ProductoVeterinario.nombre_busqueda.like(patron),
            ProductoVeterinario.principio_busqueda.like(patron),
        )
    )
    return list(db.scalars(q.order_by(ProductoVeterinario.nombre).limit(MAX_RESULTADOS + 1)).all())


def responder(db: Session, texto: str | None) -> str:
    productos = buscar(db, texto or "")
    hay_registro = db.scalar(select(ProductoVeterinario).limit(1))
    if hay_registro is None:
        return "Todavía no tengo cargado el registro de productos veterinarios de SENASA."
    if not productos:
        # Mensaje fijo: no repetimos lo que escribió la IA.
        return (
            "No encontré ese producto en el registro de SENASA que tengo cargado "
            f"(datos al {hay_registro.fecha_datos.strftime('%d/%m/%Y')}).\n"
            "Que no aparezca acá no confirma que no esté registrado. Podés verificarlo en:\n"
            f"{hay_registro.url}"
        )
    lineas = []
    for p in productos[:MAX_RESULTADOS]:
        lineas.append(f"• *{p.nombre}*")
        lineas.append(f"  Registro SENASA N° {p.registro}")
        if p.titular:
            lineas.append(f"  Titular: {p.titular}")
        if p.principio_activo:
            lineas.append(f"  Principio activo: {p.principio_activo}")
        lineas.append(f"  Estado: {p.estado or 'no informado'}")
    if len(productos) > MAX_RESULTADOS:
        lineas.append("_Hay más coincidencias. Escribí el nombre más completo._")
    primero = productos[0]
    lineas.append(
        f"\nFuente: {primero.fuente}, datos al {primero.fecha_datos.strftime('%d/%m/%Y')}\n{primero.url}\n"
    )
    return "\n".join(lineas) + "\n" + AVISO


def main() -> None:
    from app.db import SessionLocal, crear_tablas

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="python -m app.senasa")
    sub = parser.add_subparsers(dest="comando", required=True)
    cargar = sub.add_parser("cargar")
    cargar.add_argument("csv")
    cargar.add_argument("--fecha", required=True, help="fecha de los datos según SENASA, YYYY-MM-DD")
    cargar.add_argument("--url", required=True, help="página oficial de SENASA de donde salen los datos")
    ver = sub.add_parser("ver")
    ver.add_argument("texto")
    args = parser.parse_args()

    crear_tablas()
    with SessionLocal() as db:
        if args.comando == "cargar":
            with open(args.csv, encoding="utf-8") as f:
                n = reemplazar_registro(db, list(csv.DictReader(f)), date.fromisoformat(args.fecha), args.url)
            db.commit()
            print(f"{n} productos cargados")
        else:
            print(responder(db, args.texto))


if __name__ == "__main__":
    main()
