"""Precios de referencia de fuentes oficiales y mercados regulados.

Cómo funciona:
- Cada fuente es una clase con `obtener()` que descarga y lee la página oficial y
  devuelve los precios. Se registran en FUENTES.
- `python -m app precios actualizar` corre todas las fuentes y guarda en la tabla
  `cotizaciones` (en producción, como cron de Railway una o dos veces por día).
- `python -m app precios cargar archivo.csv` carga precios a mano (para probar o si
  una fuente cambia su página).
- El bot responde SOLO con lo que está en la tabla, siempre con fuente, fecha y link.
  El modelo de lenguaje nunca escribe ni ve precios: solo detecta qué producto se pide.

Para agregar una fuente:

    class PizarraRosario(Fuente):
        nombre = "Cámara Arbitral de Cereales - Bolsa de Comercio de Rosario"
        url = "https://www.cac.bcr.com.ar/es/precios-de-pizarra"
        rubro = "granos"

        def obtener(self, cliente: httpx.Client) -> list[dict[str, Any]]:
            html = cliente.get(self.url).text
            ...  # leer la tabla
            return [{"producto": "soja", "plaza": "Rosario", "valor": 300000,
                     "moneda": "ARS", "unidad": "t", "fecha": date(2026, 10, 9),
                     "incluye_impuestos": False,
                     "costos_adicionales": "Precio orientativo, sin IVA ni gastos comerciales"}]

    FUENTES.append(PizarraRosario())
"""

import csv
import logging
import re
from datetime import date, datetime, timedelta
from html import unescape
from typing import Any, ClassVar

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fuentes.oficiales import es_oficial
from app.infra.config import config
from app.infra.modelos import Cotizacion
from app.infra.texto import sin_tildes

log = logging.getLogger(__name__)


def normalizar_producto(texto: str | None) -> str | None:
    """ "Maíz" -> "maiz", "Novillos" -> "novillo"."""
    if not texto:
        return None
    texto = sin_tildes(str(texto).strip().lower())
    if texto.endswith("s") and len(texto) > 3:
        texto = texto[:-1]
    return texto or None


class Fuente:
    nombre: str = ""
    url: str = ""
    rubro: str = ""

    def obtener(self, cliente: httpx.Client) -> list[dict[str, Any]]:
        raise NotImplementedError


# --- Lectores de las fuentes ------------------------------------------------
#
# Cada lector separa la descarga (`obtener`) de la lectura del HTML (`leer`), para
# poder probar la lectura contra los archivos de tests/fixtures/ sin salir a internet.


def _a_numero(texto: str) -> float:
    """Pasa un número escrito como en Argentina a float: "$560.000,00" -> 560000.0."""
    limpio = re.sub(r"[^\d,.]", "", texto or "")
    limpio = limpio.replace(".", "").replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", limpio):
        raise ValueError(f"No pude leer el número {texto!r}")
    return float(limpio)


def _texto_plano(fragmento: str) -> str:
    """Saca las etiquetas y normaliza los espacios de un trozo de HTML."""
    texto = unescape(re.sub(r"<[^>]+>", " ", fragmento)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", texto).strip()


def _celdas(fila: str) -> list[str]:
    return [_texto_plano(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", fila, re.S | re.I)]


class PizarraRosario(Fuente):
    """Precios de pizarra de la Cámara Arbitral de Cereales (Bolsa de Comercio de Rosario).

    La página muestra un panel por grano con el precio del día en $/t para la zona
    Rosario. Cuando la Cámara no fijó pizarra el panel dice "S/C" y, si la hay, al lado
    aparece la estimación entre paréntesis, "(E)". El valor en dólares que publica al pie
    de cada panel es, según la propia página, "sólo a título informativo", así que se
    guarda el precio en pesos, que es la pizarra.
    """

    nombre = "Cámara Arbitral de Cereales - Bolsa de Comercio de Rosario"
    url = "https://www.cac.bcr.com.ar/es/precios-de-pizarra"
    rubro = "granos"
    plaza = "Rosario"

    def obtener(self, cliente: httpx.Client) -> list[dict[str, Any]]:
        respuesta = cliente.get(self.url)
        respuesta.raise_for_status()
        return self.leer(respuesta.content.decode("utf-8"))

    def leer(self, pagina: str) -> list[dict[str, Any]]:
        encontrada = re.search(r"Precios Pizarra del d[ií]a\s*(\d{2}/\d{2}/\d{4})", pagina)
        if not encontrada:
            raise ValueError("No encontré la fecha de la pizarra; la página cambió")
        fecha = datetime.strptime(encontrada.group(1), "%d/%m/%Y").date()

        pie = re.search(r'class="price-board-footer">\s*<div>(.*?)</div>', pagina, re.S)
        if not pie:
            raise ValueError("No encontré las condiciones al pie de la pizarra; la página cambió")
        # La primera oración es la que dice en qué condiciones vale el precio; lo que sigue
        # explica la conversión a dólares, que no usamos.
        condiciones = _texto_plano(pie.group(1)).split(". ")[0].rstrip(".") + "."
        if not re.search(r"impuesto|iva", condiciones, re.I):
            condiciones += " La fuente no aclara si incluye impuestos."

        precios = []
        bloques = pagina.split('<div class="board board-')[1:]
        for bloque in bloques:
            corte = bloque.find('class="price-board-footer"')
            if corte != -1:
                bloque = bloque[:corte]
            titulo = re.search(r"<h3>(.*?)</h3>", bloque, re.S)
            precio = re.search(r'class="price">(.*?)</div>', bloque, re.S)
            if not titulo or not precio:
                continue
            producto = _texto_plano(titulo.group(1))
            if not producto:
                continue
            estimado = re.search(r'class="price-sc-estimated">(.*?)</span>', precio.group(1), re.S)
            if estimado:
                valor, aclaracion = (
                    estimado.group(1),
                    (" Sin cotización (S/C) ese día: la Cámara publicó un valor estimado (E)."),
                )
            elif "S/C" in _texto_plano(precio.group(1)):
                # Sin cotización y sin estimación: ese día no hay precio para este grano.
                continue
            else:
                valor, aclaracion = precio.group(1), ""
            precios.append(
                {
                    "producto": producto,
                    "plaza": self.plaza,
                    "valor": _a_numero(_texto_plano(valor)),
                    "moneda": "ARS",
                    "unidad": "t",
                    "fecha": fecha,
                    "incluye_impuestos": None,
                    "costos_adicionales": condiciones + aclaracion,
                }
            )

        if not precios:
            raise ValueError("No pude leer ningún precio de la pizarra; la página cambió")
        return precios


class HaciendaCanuelas(Fuente):
    """Precios por categoría del Mercado Agroganadero de Cañuelas.

    La página devuelve la planilla de una rueda (un día) y hay que pedírsela por POST con
    el rango de fechas. Los sábados, domingos y feriados viene vacía, así que se prueba
    día por día hacia atrás hasta encontrar la última rueda con operaciones.

    De cada categoría (NOVILLOS, NOVILLITOS, VAQUILLONAS, VACAS, TOROS, ...) se guarda el
    promedio por kg vivo que publica la planilla, y se verifica contra el importe y los
    kilos totales de sus subcategorías: si no coinciden, la lectura falla en lugar de
    guardar un número dudoso.
    """

    nombre = "Mercado Agroganadero de Cañuelas"
    url = "https://www.mercadoagroganadero.com.ar/dll/hacienda1.dll/haciinfo000502"
    rubro = "hacienda"
    plaza = "Cañuelas"
    DIAS_ATRAS = 8
    # El formulario de la página manda estos campos; sin identificarse alcanza.
    CAMPOS: ClassVar[dict[str, str]] = {
        "ID": "",
        "CP": "",
        "FLASH": "",
        "USUARIO": "SIN IDENTIFICAR",
        "OPCIONMENU": "",
        "OPCIONSUBMENU": "",
    }

    def obtener(self, cliente: httpx.Client) -> list[dict[str, Any]]:
        hoy = datetime.now(config.zona_horaria).date()
        for atras in range(self.DIAS_ATRAS):
            dia = (hoy - timedelta(days=atras)).strftime("%d/%m/%Y")
            respuesta = cliente.post(self.url, data={**self.CAMPOS, "txtFechaIni": dia, "txtFechaFin": dia})
            respuesta.raise_for_status()
            # La página declara windows-1252 en su <meta>, pero no en la respuesta HTTP.
            precios = self.leer(respuesta.content.decode("windows-1252"))
            if precios:
                return precios
        raise ValueError(f"El MAG no publicó ninguna rueda en los últimos {self.DIAS_ATRAS} días")

    def leer(self, pagina: str) -> list[dict[str, Any]]:
        """Devuelve los precios de la rueda, o [] si ese día no hubo operaciones."""
        encabezado = re.search(
            r"PRECIOS POR CATEGORIA.*?DESDE EL \w+ (\d{2}/\d{2}/\d{4}) AL \w+ (\d{2}/\d{2}/\d{4})"
            # entre la fecha y la aclaración puede haber un <BR> y un <FONT> de color
            r"(?:\s|<[^>]*>)*PRECIOS (DEFINITIVOS|PROVISORIOS)",
            pagina,
            re.S | re.I,
        )
        if not encabezado:
            raise ValueError("No encontré el encabezado de la planilla del MAG; la página cambió")
        desde, hasta, estado = encabezado.groups()
        if desde != hasta:
            raise ValueError(f"La planilla abarca más de un día ({desde} a {hasta})")
        fecha = datetime.strptime(desde, "%d/%m/%Y").date()

        grupos: dict[str, dict[str, Any]] = {}
        actual = None
        for fila in re.findall(r"<tr[^>]*>(.*?)</tr>", pagina, re.S | re.I):
            celdas = _celdas(fila)
            if len(celdas) < 9:
                continue
            nombre = celdas[0]
            if nombre.lower().startswith("totales"):
                break
            if nombre:
                actual = nombre.split()[0].upper()
                grupo = grupos.setdefault(actual, {"importe": 0.0, "kilos": 0.0, "cabezas": 0, "publicado": None})
                grupo["importe"] += _a_numero(celdas[6])
                grupo["kilos"] += _a_numero(celdas[7])
                grupo["cabezas"] += int(_a_numero(celdas[5]))
            elif actual and re.fullmatch(r"[\d.,]+", celdas[3] or ""):
                # Fila de subtotal de la categoría: el promedio que publica la planilla.
                grupos[actual]["publicado"] = _a_numero(celdas[3])

        if not grupos:
            return []

        aclaracion = (
            f"Precios {estado.lower()} publicados por el MAG para la rueda del día. "
            "Promedio de la categoría por kg vivo. "
            "Categorías según RESOL-2018-32-APN-SGA#MPYT. "
            "La fuente no aclara si incluye impuestos, comisiones o fletes."
        )
        precios = []
        for categoria, datos in grupos.items():
            publicado, kilos = datos["publicado"], datos["kilos"]
            if publicado is None or kilos <= 0 or datos["cabezas"] <= 0:
                raise ValueError(f"La planilla del MAG no cierra para {categoria}: {datos}")
            # El promedio publicado tiene que ser el importe sobre los kilos.
            calculado = datos["importe"] / kilos
            if abs(calculado - publicado) / publicado > 0.005:
                raise ValueError(
                    f"El promedio de {categoria} no coincide con importe/kilos "
                    f"({publicado} vs {calculado:.3f}); la planilla cambió"
                )
            precios.append(
                {
                    "producto": categoria,
                    "plaza": self.plaza,
                    "valor": publicado,
                    "moneda": "ARS",
                    "unidad": "kg vivo",
                    "fecha": fecha,
                    "incluye_impuestos": None,
                    "costos_adicionales": aclaracion,
                }
            )
        return precios


FUENTES: list[Fuente] = [PizarraRosario(), HaciendaCanuelas()]


MONEDAS = {"ARS": "$", "USD": "US$"}


def _moneda(valor: object) -> str:
    moneda = str(valor or "ARS").strip().upper()
    if moneda not in MONEDAS:
        raise ValueError(f"Moneda no soportada: {valor}")
    return moneda


def _si_no(valor: object) -> bool | None:
    """True/False si la fuente lo informa; None si no dice nada."""
    if isinstance(valor, bool) or valor is None:
        return valor
    texto = str(valor).strip().lower()
    if texto in ("si", "sí", "true", "1"):
        return True
    if texto in ("no", "false", "0"):
        return False
    return None


def guardar(db: Session, fuente: str, url: str, rubro: str, precios: list[dict[str, Any]]) -> int:
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
        existente.moneda = _moneda(p.get("moneda"))
        existente.unidad = str(p["unidad"]).strip()
        existente.incluye_impuestos = _si_no(p.get("incluye_impuestos"))
        existente.costos_adicionales = str(p.get("costos_adicionales") or "").strip() or None
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


def cargar_csv(db: Session, ruta: str) -> dict[str, int]:
    """Columnas: fuente,url,rubro,producto,plaza,valor,moneda,unidad,fecha,incluye_impuestos,costos_adicionales.

    fecha en YYYY-MM-DD; incluye_impuestos: si / no / vacío si la fuente no lo informa.
    """
    with open(ruta, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    grupos: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for fila in filas:
        grupos.setdefault((fila["fuente"], fila["url"], fila["rubro"]), []).append(fila)
    return {fuente: guardar(db, fuente, url, rubro, precios) for (fuente, url, rubro), precios in grupos.items()}
