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

También se puede traer el registro solo, desde la consulta pública de SENASA (ver
`descargar` más abajo para lo que publica y lo que no):

    python -m app.senasa actualizar

En Railway eso se programa como Cron Job, igual que los precios.
"""

import argparse
import csv
import logging
import re
import unicodedata
from datetime import date, datetime
from urllib.parse import urlparse

import httpx
import xlrd
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app import config
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


# --- Descarga del registro desde la consulta pública de SENASA ---------------
#
# SENASA tiene dos consultas públicas de productos veterinarios:
#
# 1. El Vademécum nuevo (aps2.senasa.gov.ar/vademecumVet/app/publico). Tiene principio
#    activo e indicaciones, pero su API está detrás del SSO de SENASA (todo /api/...
#    redirige al login JOSSO), así que no se puede leer sin credenciales.
# 2. La "Consulta Pública de Productos Veterinarios" del sistema ADT, que es la que se
#    usa acá: es pública, no pide clave y tiene un botón "Exportar a CSV".
#
# Dos cosas para tener en cuenta de esa exportación:
# - El archivo se llama .csv pero es un Excel 97-2003 (empieza con la firma OLE2), por
#   eso se lee con xlrd.
# - Trae 5 columnas: certificado, nombre comercial, expediente, firma y "propio". NO
#   trae principio activo ni estado del registro, así que esos campos quedan vacíos:
#   el bot dice "no informado" en lugar de inventarlos.
#
# La consulta tampoco informa a qué fecha están los datos, así que `actualizar` usa la
# fecha de la descarga. Es lo que después el bot muestra como "datos al ...".

URL_CONSULTA = "https://aps2.senasa.gov.ar/adt/pages/public/farmacos/consultaProductosFarmacos.faces"
# Página oficial (.gob.ar) desde donde una persona llega a esa misma consulta.
URL_OFICIAL = (
    "https://www.argentina.gob.ar/senasa/programas-sanitarios/"
    "productos-veterinarios-fitosanitarios-y-fertilizantes/listados-oficiales"
)
COLUMNAS_ESPERADAS = ["Nro.Certificado", "Nombre comercial", "Expediente", "Nombre de firma", "Propio"]
MINIMO_PRODUCTOS = 100  # si vienen menos, algo salió mal y no tocamos el registro
CAMPOS_BUSQUEDA = ("_idJsp5", "_idJsp7", "_idJsp9", "_idJsp11")  # certificado, nombre, cuit, firma


def _campos_del_formulario(pagina: str) -> dict:
    """Los hidden del formulario JSF (jsf_tree/jsf_state) más los filtros, vacíos."""
    campos = {}
    for etiqueta in re.findall(r'<input[^>]*type="hidden"[^>]*>', pagina):
        nombre = re.search(r'name="([^"]+)"', etiqueta)
        valor = re.search(r'value="([^"]*)"', etiqueta)
        if nombre:
            campos[nombre.group(1)] = valor.group(1) if valor else ""
    if "jsf_state_64" not in campos:
        raise ValueError("La consulta de SENASA no devolvió el estado del formulario; la página cambió")
    campos.update({f"Formulario:{c}": "" for c in CAMPOS_BUSQUEDA})
    campos["Formulario_SUBMIT"] = "1"
    return campos


def descargar(cliente: httpx.Client) -> list[dict]:
    """Trae todos los productos de la consulta pública de SENASA.

    Hace lo mismo que una persona: abre la consulta, aprieta "Consultar" sin filtros y
    después "Exportar a CSV".
    """
    pagina = cliente.get(URL_CONSULTA).content.decode("ISO-8859-1")

    buscar_todo = _campos_del_formulario(pagina)
    buscar_todo["Formulario:cmdConsultarProductos"] = "Consultar"
    resultados = cliente.post(URL_CONSULTA, data=buscar_todo).content.decode("ISO-8859-1")

    exportar = _campos_del_formulario(resultados)
    exportar["Formulario:exportarConsultaACSV"] = "Exportar a CSV"
    descarga = cliente.post(URL_CONSULTA, data=exportar).content

    if not descarga.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValueError("La exportación de SENASA no es un Excel 97-2003; la página cambió")

    hoja = xlrd.open_workbook(file_contents=descarga).sheet_by_index(0)
    encabezados = [str(c.value).strip() for c in hoja.row(0)]
    if encabezados != COLUMNAS_ESPERADAS:
        raise ValueError(f"Las columnas de SENASA cambiaron: {encabezados}")

    filas = []
    for i in range(1, hoja.nrows):
        certificado, nombre = str(hoja.cell_value(i, 0)).strip(), str(hoja.cell_value(i, 1)).strip()
        if not certificado or not nombre:
            continue
        filas.append({
            "nombre": nombre,
            "registro": certificado,
            "titular": str(hoja.cell_value(i, 3)).strip() or None,
            # La consulta pública no publica ninguno de los dos.
            "principio_activo": None,
            "estado": None,
        })
    if len(filas) < MINIMO_PRODUCTOS:
        raise ValueError(f"SENASA devolvió solo {len(filas)} productos; no reemplazo el registro")
    return filas


def actualizar(db: Session, fecha_datos: date, url: str = URL_OFICIAL) -> int:
    with httpx.Client(timeout=180, follow_redirects=True, headers={"User-Agent": "campo-bot/1.0"}) as cliente:
        filas = descargar(cliente)
    return reemplazar_registro(db, filas, fecha_datos, url)


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
    traer = sub.add_parser("actualizar", help="descarga la consulta pública de SENASA")
    traer.add_argument("--fecha", help="fecha de los datos; por defecto, la de hoy")
    traer.add_argument("--url", default=URL_OFICIAL, help="página oficial que se guarda como fuente")
    ver = sub.add_parser("ver")
    ver.add_argument("texto")
    args = parser.parse_args()

    crear_tablas()
    with SessionLocal() as db:
        if args.comando == "actualizar":
            fecha = date.fromisoformat(args.fecha) if args.fecha else datetime.now(config.ZONA_HORARIA).date()
            n = actualizar(db, fecha, args.url)
            db.commit()
            print(f"{n} productos cargados (datos al {fecha.strftime('%d/%m/%Y')})")
        elif args.comando == "cargar":
            with open(args.csv, encoding="utf-8") as f:
                n = reemplazar_registro(db, list(csv.DictReader(f)), date.fromisoformat(args.fecha), args.url)
            db.commit()
            print(f"{n} productos cargados")
        else:
            print(responder(db, args.texto))


if __name__ == "__main__":
    main()
