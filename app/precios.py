"""Precios de referencia de fuentes oficiales y mercados regulados.

Cómo funciona:
- Cada fuente es una clase con `obtener()` que descarga y lee la página oficial y
  devuelve los precios. Se registran en FUENTES.
- `python -m app.precios actualizar` corre todas las fuentes y guarda en la tabla
  `cotizaciones` (en producción, como cron de Railway una o dos veces por día).
- `python -m app.precios cargar archivo.csv` carga precios a mano (para probar o si
  una fuente cambia su página).
- El bot responde SOLO con lo que está en la tabla, siempre con fuente, fecha y link.
  El modelo de lenguaje nunca escribe ni ve precios: solo detecta qué producto se pide.

Para agregar una fuente:

    class PizarraRosario(Fuente):
        nombre = "Cámara Arbitral de Cereales - Bolsa de Comercio de Rosario"
        url = "https://www.cac.bcr.com.ar/es/precios-de-pizarra"
        rubro = "granos"

        def obtener(self, cliente: httpx.Client) -> list[dict]:
            html = cliente.get(self.url).text
            ...  # leer la tabla
            return [{"producto": "soja", "plaza": "Rosario", "valor": 300000,
                     "unidad": "$/t", "fecha": date(2026, 10, 9)}]

    FUENTES.append(PizarraRosario())
"""

import csv
import logging
import sys
import unicodedata
from datetime import date, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.models import Cotizacion

log = logging.getLogger(__name__)

# Solo se aceptan precios cuyo link sea de uno de estos dominios (o subdominios).
DOMINIOS_OFICIALES = (
    "gob.ar",  # Secretaría de Agricultura, SENASA, INTA, datos.gob.ar...
    "bcr.com.ar",  # Bolsa de Comercio de Rosario y su Cámara Arbitral
    "mercadoagroganadero.com.ar",  # Mercado Agroganadero de Cañuelas
    "matba-rofex.com.ar",
    "a3mercados.com.ar",
    "bolsadecereales.com",  # Bolsa de Cereales de Buenos Aires
    "bcp.org.ar",  # Bolsa de Cereales y Productos de Bahía Blanca
)

AVISO = "_Valores de referencia publicados por la fuente. No son una recomendación de compra o venta._"


def es_oficial(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return urlparse(url).scheme == "https" and any(
        host == d or host.endswith("." + d) for d in DOMINIOS_OFICIALES
    )


def normalizar_producto(texto: str | None) -> str | None:
    """"Maíz" -> "maiz", "Novillos" -> "novillo"."""
    if not texto:
        return None
    texto = unicodedata.normalize("NFKD", str(texto).strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    if texto.endswith("s") and len(texto) > 3:
        texto = texto[:-1]
    return texto or None


class Fuente:
    nombre: str = ""
    url: str = ""
    rubro: str = ""

    def obtener(self, cliente: httpx.Client) -> list[dict]:
        raise NotImplementedError


# Las fuentes reales se agregan acá (ver el docstring del módulo).
FUENTES: list[Fuente] = []


def guardar(db: Session, fuente: str, url: str, rubro: str, precios: list[dict]) -> int:
    if not es_oficial(url):
        raise ValueError(f"La URL {url} no es de una fuente oficial habilitada")
    guardados = 0
    for p in precios:
        producto = normalizar_producto(p.get("producto"))
        fecha = p.get("fecha")
        if isinstance(fecha, str):
            fecha = date.fromisoformat(fecha)
        valor = float(p["valor"])
        if not producto or not isinstance(fecha, date) or valor <= 0:
            log.warning("Precio descartado de %s: %s", fuente, p)
            continue
        plaza = (p.get("plaza") or None) and str(p["plaza"]).strip()
        existente = db.scalar(
            select(Cotizacion).where(
                Cotizacion.fuente == fuente,
                Cotizacion.producto == producto,
                Cotizacion.plaza.is_(None) if plaza is None else Cotizacion.plaza == plaza,
                Cotizacion.fecha == fecha,
            )
        )
        if existente is None:
            existente = Cotizacion(fuente=fuente, producto=producto, plaza=plaza, fecha=fecha)
            db.add(existente)
        existente.rubro = rubro
        existente.valor = valor
        existente.unidad = str(p["unidad"]).strip()
        existente.url = url
        guardados += 1
    db.flush()
    return guardados


def actualizar(db: Session) -> None:
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "campo-bot/1.0"}) as cliente:
        for fuente in FUENTES:
            try:
                n = guardar(db, fuente.nombre, fuente.url, fuente.rubro, fuente.obtener(cliente))
                db.commit()
                log.info("%s: %d precios", fuente.nombre, n)
            except Exception:
                db.rollback()
                log.exception("Falló la fuente %s", fuente.nombre)


def ultimas(db: Session, producto: str | None, rubro: str | None) -> list[Cotizacion]:
    """El último precio publicado de cada (fuente, producto, plaza)."""
    filtro = []
    if producto := normalizar_producto(producto):
        filtro.append(Cotizacion.producto == producto)
    elif rubro:
        filtro.append(Cotizacion.rubro == rubro)
    ultima_fecha = (
        select(
            Cotizacion.fuente, Cotizacion.producto, Cotizacion.plaza,
            func.max(Cotizacion.fecha).label("fecha"),
        )
        .where(*filtro)
        .group_by(Cotizacion.fuente, Cotizacion.producto, Cotizacion.plaza)
        .subquery()
    )
    q = select(Cotizacion).join(
        ultima_fecha,
        (Cotizacion.fuente == ultima_fecha.c.fuente)
        & (Cotizacion.producto == ultima_fecha.c.producto)
        & ((Cotizacion.plaza == ultima_fecha.c.plaza) | (Cotizacion.plaza.is_(None) & ultima_fecha.c.plaza.is_(None)))
        & (Cotizacion.fecha == ultima_fecha.c.fecha),
    )
    return list(db.scalars(q.order_by(Cotizacion.producto, Cotizacion.plaza)).all())


_NOMBRES = {"maiz": "Maíz", "girasol": "Girasol", "ternero": "Ternero", "vaquillona": "Vaquillona"}


def _numero(valor: float) -> str:
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return texto.removesuffix(",00")


def responder(db: Session, producto: str | None, rubro: str | None, hoy: date) -> str:
    cotizaciones = ultimas(db, producto, rubro)
    if not cotizaciones:
        # Mensaje fijo: no repetimos lo que escribió la IA.
        return (
            "No tengo precios cargados de ese producto de una fuente oficial. "
            "Solo informo precios que publican organismos oficiales o mercados regulados."
        )
    lineas = []
    por_fuente: dict[tuple[str, str], list[Cotizacion]] = {}
    for c in cotizaciones:
        por_fuente.setdefault((c.fuente, c.url), []).append(c)
    for (fuente, url), lista in por_fuente.items():
        for c in lista[:20]:
            plaza = f" ({c.plaza})" if c.plaza else ""
            viejo = " ⚠️ dato no actualizado" if (hoy - c.fecha).days > config.DIAS_PRECIO_VIGENTE else ""
            lineas.append(
                f"• {_NOMBRES.get(c.producto, c.producto.capitalize())}{plaza}: *{_numero(c.valor)} {c.unidad}* "
                f"· {c.fecha.strftime('%d/%m/%Y')}{viejo}"
            )
        lineas.append(f"Fuente: {fuente}\n{url}\n")
    return "\n".join(lineas) + "\n" + AVISO


def _cargar_csv(db: Session, ruta: str) -> None:
    """Columnas: fuente,url,rubro,producto,plaza,valor,unidad,fecha (fecha YYYY-MM-DD)."""
    with open(ruta, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    grupos: dict[tuple[str, str, str], list[dict]] = {}
    for fila in filas:
        grupos.setdefault((fila["fuente"], fila["url"], fila["rubro"]), []).append(fila)
    for (fuente, url, rubro), precios in grupos.items():
        print(f"{fuente}: {guardar(db, fuente, url, rubro, precios)} precios")
    db.commit()


def main() -> None:
    from app.db import SessionLocal, crear_tablas

    logging.basicConfig(level=logging.INFO)
    crear_tablas()
    comando = sys.argv[1] if len(sys.argv) > 1 else ""
    with SessionLocal() as db:
        if comando == "actualizar":
            if not FUENTES:
                print("No hay fuentes registradas en app/precios.py (FUENTES está vacía).")
            actualizar(db)
        elif comando == "cargar" and len(sys.argv) > 2:
            _cargar_csv(db, sys.argv[2])
        elif comando == "ver":
            print(responder(db, sys.argv[2] if len(sys.argv) > 2 else None, None, datetime.now(config.ZONA_HORARIA).date()))
        else:
            print("Uso: python -m app.precios actualizar | cargar archivo.csv | ver [producto]")


if __name__ == "__main__":
    main()
