"""Respuesta a los pedidos de precios: solo lo que está en la tabla de cotizaciones.

El modelo de lenguaje nunca escribe ni ve precios: solo detecta qué producto se pide.
Cada precio sale con su fuente, la fecha de publicación, la moneda y el link.
"""

import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.fuentes.precios import MONEDAS, normalizar_producto
from app.infra.config import config
from app.infra.modelos import Cotizacion
from app.salidas.whatsapp import numero

AVISO = "_Valores de referencia publicados por la fuente. No son una recomendación de compra o venta._"


def ultimas(db: Session, producto: str | None, rubro: str | None) -> list[Cotizacion]:
    """El último precio publicado de cada (fuente, producto, plaza)."""
    filtro = []
    if producto := normalizar_producto(producto):
        filtro.append(Cotizacion.producto == producto)
    elif rubro:
        filtro.append(Cotizacion.rubro == rubro)
    ultima_fecha = (
        select(
            Cotizacion.fuente,
            Cotizacion.producto,
            Cotizacion.plaza,
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


def _costos(c: Cotizacion) -> str:
    partes = []
    if c.incluye_impuestos is True:
        partes.append("Incluye impuestos.")
    elif c.incluye_impuestos is False:
        partes.append("No incluye impuestos (IVA).")
    if c.costos_adicionales:
        partes.append(c.costos_adicionales.rstrip(".") + ".")
    if not partes:
        return "La fuente no informa si incluye impuestos u otros costos."
    return " ".join(partes)


_ICONOS = {"soja": "🫘", "maiz": "🌽", "trigo": "🌾", "girasol": "🌻", "sorgo": "🌾", "cebada": "🌾"}


def _lineas_cotizacion(c: Cotizacion, hoy: date) -> list[str]:
    plaza = f" · {c.plaza}" if c.plaza else ""
    nombre = _NOMBRES.get(c.producto, c.producto.capitalize())
    icono = _ICONOS.get(c.producto, "🐂" if c.rubro == "hacienda" else "📈")
    dias = (hoy - c.fecha).days
    viejo = (
        f"\n      ⚠️ _Dato de hace {dias} días, puede no estar actualizado_" if dias > config.dias_precio_vigente else ""
    )
    return [
        f"{icono} *{nombre}*{plaza}",
        f"      *{MONEDAS[c.moneda]} {numero(c.valor)}* por {c.unidad} ({c.moneda})",
        f"      📅 Publicado el {c.fecha.strftime('%d/%m/%Y')}{viejo}",
        f"      ℹ️ _{_costos(c)}_",
        "",
    ]


SIN_PRECIOS = (
    "🔍 No tengo precios cargados de ese producto de una fuente oficial.\n"
    "_Solo informo precios que publican organismos oficiales o mercados regulados._"
)


def responder(db: Session, producto: str | None, rubro: str | None, hoy: date) -> str:
    return responder_varios(db, [(producto, rubro)], hoy)


def responder_varios(db: Session, pedidos: list[tuple[str | None, str | None]], hoy: date) -> str:
    """Precios de varios productos en una sola respuesta, agrupados por fuente."""
    cotizaciones: dict[int, Cotizacion] = {}
    faltan: list[str] = []
    for producto, rubro in pedidos:
        encontradas = ultimas(db, producto, rubro)
        if not encontradas:
            nombre = normalizar_producto(producto) or ""
            # Solo nombramos lo que falta si es una palabra simple (no repetimos texto libre de la IA).
            faltan.append(_NOMBRES.get(nombre, nombre.capitalize()) if re.fullmatch(r"[a-zñ ]{2,20}", nombre) else "")
        cotizaciones.update({c.id: c for c in encontradas})
    if not cotizaciones:
        return SIN_PRECIOS

    lineas = ["💲 *PRECIOS DE REFERENCIA*", ""]
    por_fuente: dict[tuple[str, str], list[Cotizacion]] = {}
    for c in cotizaciones.values():
        por_fuente.setdefault((c.fuente, c.url), []).append(c)
    fuentes = []
    for (fuente, url), lista in por_fuente.items():
        for c in lista[:20]:
            lineas += _lineas_cotizacion(c, hoy)
        fuentes.append(f"📰 _Fuente: {fuente}_\n🔗 {url}")
    if faltan:
        nombres = ", ".join(f for f in faltan if f)
        lineas.append(
            f"🔍 No tengo precios oficiales cargados de: {nombres}.\n"
            if nombres
            else "🔍 De algún producto que pediste no tengo precios oficiales cargados.\n"
        )
    return "\n".join(lineas) + "────────────\n" + "\n\n".join(fuentes) + "\n\n" + AVISO
