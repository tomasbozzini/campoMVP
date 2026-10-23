"""Cómo se ven los mensajes del bot en WhatsApp.

WhatsApp solo entiende *negrita*, _cursiva_, ~tachado~ y saltos de línea, así que la
jerarquía se arma con títulos en mayúscula, íconos por tipo de registro, sangría y
líneas separadoras. Todo el texto lo arma el código: la IA no escribe nada de esto.
"""

from collections import defaultdict
from collections.abc import Callable
from datetime import date
from typing import Any

from app.infra.modelos import Evento

SEPARADOR = "────────────"
SANGRIA = "      "

# Lo que un módulo le suma al detalle de los registros de un tipo, con los datos que guarda en
# `extra` ("Preñada cabeza · CC 3" en un tacto): tipo -> función. Lo registra el módulo al
# cargarse; sirve para WhatsApp, el PDF y la planilla.
DETALLES: dict[str, Callable[[Evento], list[str]]] = {}

NOMBRES_TIPO = {
    "vacunacion": "Vacunación",
    "desparasitacion": "Desparasitación",
    "inseminacion": "Inseminación",
    "paricion": "Parición",
    "fumigacion": "Fumigación",
    "fertilizacion": "Fertilización",
}

ICONOS_TIPO = {
    "vacunacion": "💉",
    "desparasitacion": "🪱",
    "tratamiento": "💊",
    "nacimiento": "🐣",
    "muerte": "🔻",
    "compra": "🛒",
    "venta": "💰",
    "traslado": "🚚",
    "pesaje": "⚖️",
    "servicio": "🐂",
    "inseminacion": "🧬",
    "tacto": "🩺",
    "paricion": "🍼",
    "destete": "🍼",
    "lluvia": "🌧️",
    "siembra": "🌱",
    "cosecha": "🌾",
    "fumigacion": "🧴",
    "fertilizacion": "🧪",
    "mantenimiento": "🔧",
}

_DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def nombre_tipo(tipo: str) -> str:
    return NOMBRES_TIPO.get(tipo, tipo.capitalize())


def icono(tipo: str) -> str:
    return ICONOS_TIPO.get(tipo, "📌")


def fecha_corta(d: date) -> str:
    return f"{_DIAS[d.weekday()]} {d.strftime('%d/%m/%Y')}"


def dia_semana(d: date) -> str:
    """ "jueves", "sábado" """
    return ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")[d.weekday()]


def singular(palabra: str) -> str:
    """ "vacas" -> "vaca", "animales" -> "animal". Alcanza para las categorías que usamos."""
    if palabra.endswith("es") and len(palabra) > 3:
        return palabra[:-2]
    if palabra.endswith("s") and len(palabra) > 2:
        return palabra[:-1]
    return palabra


def numero(valor: float) -> str:
    """310000 -> "310.000"; 2.5 -> "2,5" (como se escribe en Argentina)."""
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return texto.removesuffix(",00")


def titulo(e: Evento) -> str:
    """💉 *Vacunación* · aftosa"""
    texto = f"{icono(e.tipo)} *{nombre_tipo(e.tipo)}*"
    return texto + (f" · {e.producto}" if e.producto else "")


def detalle(e: Evento) -> str:
    """20 vacas · Lote 3 · 2 ml"""
    partes = []
    if e.cantidad_animales:
        nombre = e.categoria_animal or "animales"
        partes.append(f"{e.cantidad_animales} {singular(nombre) if e.cantidad_animales == 1 else nombre}")
    elif e.categoria_animal:
        # Un animal con caravana es uno solo: "toro", no "toros".
        partes.append(singular(e.categoria_animal) if e.caravana else e.categoria_animal)
    if e.caravana:
        partes.append(f"Caravana {e.caravana}")
    lote, destino = e.nombre_lote, e.nombre_lote_destino
    if lote and destino:
        partes.append(f"Lote {lote} → {destino}")
    elif destino:
        partes.append(f"→ Lote {destino}")
    elif lote:
        partes.append(f"Lote {lote}")
    if e.dosis:
        partes.append(e.dosis)
    if e.valor is not None:
        partes.append(f"{numero(e.valor)} {e.unidad or ''}".strip())
    if (del_modulo := DETALLES.get(e.tipo)) is not None:
        partes += del_modulo(e)
    return " · ".join(partes)


def tarjeta(e: Evento, lugar: bool = True, fecha: bool = True) -> str:
    """Un registro con su título y los datos debajo, con sangría."""
    lineas = [titulo(e)]
    if d := detalle(e):
        lineas.append(SANGRIA + d)
    pie = []
    if lugar and e.establecimiento:
        pie.append(f"📍 {e.establecimiento.nombre}")
    if fecha:
        pie.append(f"📅 {fecha_corta(e.fecha_evento)}")
    if pie:
        lineas.append(SANGRIA + " · ".join(pie))
    return "\n".join(lineas)


def tarjetas(eventos: list[Evento], lugar: bool = True, fecha: bool = True) -> str:
    return "\n\n".join(tarjeta(e, lugar, fecha) for e in eventos)


def linea(e: Evento) -> str:
    """Versión en una línea, para listas cortas de opciones: 🌧️ Lluvia · 30 mm · 📍 La Pastora · 11/10"""
    partes = [f"{icono(e.tipo)} {nombre_tipo(e.tipo)}" + (f" ({e.producto})" if e.producto else "")]
    if d := detalle(e):
        partes.append(d)
    if e.establecimiento:
        partes.append(f"📍 {e.establecimiento.nombre}")
    partes.append(e.fecha_evento.strftime("%d/%m"))
    return " · ".join(partes)


def sumas(eventos: list[Evento]) -> list[tuple[str, int | float, str]]:
    """Animales por tipo de registro y suma de valores por tipo y unidad: (tipo, total,
    "animales" o la unidad). Las cuentas las hace el código; las usan WhatsApp y el PDF."""
    animales: dict[str, int] = defaultdict(int)
    valores: dict[tuple[str, str], float] = defaultdict(float)
    for e in eventos:
        if e.cantidad_animales:
            animales[e.tipo] += e.cantidad_animales
        if e.valor is not None and e.unidad:
            valores[(e.tipo, e.unidad)] += e.valor
    return [(t, c, "animales") for t, c in animales.items()] + [(t, v, u) for (t, u), v in valores.items()]


def totales(eventos: list[Evento]) -> str | None:
    """📊 Totales: animales por tipo de registro y suma de valores por tipo y unidad. None si
    no hay nada que sumar."""
    filas = [
        f"{SANGRIA}{icono(t)} {nombre_tipo(t)}: *{c}* animales"
        if u == "animales"
        else f"{SANGRIA}{icono(t)} {nombre_tipo(t)}: *{numero(c)} {u}*"
        for t, c, u in sumas(eventos)
    ]
    return "📊 *Totales*\n" + "\n".join(filas) if filas else None


def por_dia(eventos: list[Evento], lugar: bool = True) -> str:
    """Lista agrupada por fecha, de la más reciente a la más vieja."""
    grupos: dict[date, list[Evento]] = defaultdict(list)
    for e in eventos:
        grupos[e.fecha_evento].append(e)
    bloques = []
    for dia in sorted(grupos, reverse=True):
        bloques.append(f"📅 *{fecha_corta(dia)}*\n\n" + tarjetas(grupos[dia], lugar=lugar, fecha=False))
    return "\n\n".join(bloques)


ETIQUETAS = {
    "tipo": "Tipo",
    "producto": "Producto",
    "dosis": "Dosis",
    "cantidad_animales": "Cantidad",
    "categoria_animal": "Categoría",
    "caravana": "Caravana",
    "lote": "Lote",
    "lote_destino": "Lote destino",
    "valor": "Valor",
    "unidad": "Unidad",
    "fecha_evento": "Fecha",
    "establecimiento": "Establecimiento",
    "descripcion": "Descripción",
}
# El lote y el establecimiento se comparan y se muestran por su nombre.
_POR_NOMBRE = {
    "lote": "nombre_lote",
    "lote_destino": "nombre_lote_destino",
    "establecimiento": "nombre_establecimiento",
}


def _valor(e: Evento, campo: str) -> Any:
    return getattr(e, _POR_NOMBRE.get(campo, campo))


def cambios(antes: dict[str, Any], despues: Evento) -> list[str]:
    """Qué campos cambió una corrección, para mostrar solo eso."""
    lineas = []
    for campo, etiqueta in ETIQUETAS.items():
        viejo: Any = antes.get(campo)
        nuevo: Any = _valor(despues, campo)
        if viejo == nuevo:
            continue
        if campo == "fecha_evento":
            viejo, nuevo = viejo.strftime("%d/%m/%Y"), nuevo.strftime("%d/%m/%Y")
        elif campo == "tipo":
            viejo, nuevo = nombre_tipo(viejo), nombre_tipo(nuevo)
        elif campo == "valor":
            viejo = numero(viejo) if viejo is not None else None
            nuevo = numero(nuevo) if nuevo is not None else None
        lineas.append(f"{etiqueta}: ~{viejo}~ → *{nuevo}*" if viejo not in (None, "") else f"{etiqueta}: *{nuevo}*")
    return lineas


def foto(e: Evento) -> dict[str, Any]:
    """Los valores de un registro antes de corregirlo."""
    return {campo: _valor(e, campo) for campo in ETIQUETAS}
