"""Cómo se ven los mensajes del bot en WhatsApp.

WhatsApp solo entiende *negrita*, _cursiva_, ~tachado~ y saltos de línea, así que la
jerarquía se arma con títulos en mayúscula, íconos por tipo de registro, sangría y
líneas separadoras. Todo el texto lo arma el código: la IA no escribe nada de esto.
"""

from collections import defaultdict
from datetime import date

from app.models import Evento

SEPARADOR = "────────────"
SANGRIA = "      "

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


def singular(palabra: str) -> str:
    """"vacas" -> "vaca", "animales" -> "animal". Alcanza para las categorías que usamos."""
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
    if e.lote and e.lote_destino:
        partes.append(f"Lote {e.lote} → {e.lote_destino}")
    elif e.lote_destino:
        partes.append(f"→ Lote {e.lote_destino}")
    elif e.lote:
        partes.append(f"Lote {e.lote}")
    if e.dosis:
        partes.append(e.dosis)
    if e.valor is not None:
        partes.append(f"{numero(e.valor)} {e.unidad or ''}".strip())
    return " · ".join(partes)


def tarjeta(e: Evento, lugar: bool = True, fecha: bool = True) -> str:
    """Un registro con su título y los datos debajo, con sangría."""
    lineas = [titulo(e)]
    if d := detalle(e):
        lineas.append(SANGRIA + d)
    pie = []
    if lugar and e.establecimiento:
        pie.append(f"📍 {e.establecimiento}")
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
        partes.append(f"📍 {e.establecimiento}")
    partes.append(e.fecha_evento.strftime("%d/%m"))
    return " · ".join(partes)


def por_dia(eventos: list[Evento], lugar: bool = True) -> str:
    """Lista agrupada por fecha, de la más reciente a la más vieja."""
    grupos: dict[date, list[Evento]] = defaultdict(list)
    for e in eventos:
        grupos[e.fecha_evento].append(e)
    bloques = []
    for dia in sorted(grupos, reverse=True):
        bloques.append(f"📅 *{fecha_corta(dia)}*\n\n" + tarjetas(grupos[dia], lugar=lugar, fecha=False))
    return "\n\n".join(bloques)


def cambios(antes: dict, despues: Evento) -> list[str]:
    """Qué campos cambió una corrección, para mostrar solo eso."""
    etiquetas = {
        "tipo": "Tipo", "producto": "Producto", "dosis": "Dosis", "cantidad_animales": "Cantidad",
        "categoria_animal": "Categoría", "caravana": "Caravana", "lote": "Lote",
        "lote_destino": "Lote destino", "valor": "Valor", "unidad": "Unidad",
        "fecha_evento": "Fecha", "establecimiento": "Establecimiento", "descripcion": "Descripción",
    }
    lineas = []
    for campo, etiqueta in etiquetas.items():
        viejo, nuevo = antes.get(campo), getattr(despues, campo)
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


def foto(e: Evento) -> dict:
    """Los valores de un registro antes de corregirlo."""
    campos = ("tipo", "producto", "dosis", "cantidad_animales", "categoria_animal", "caravana", "lote",
              "lote_destino", "valor", "unidad", "fecha_evento", "establecimiento", "descripcion")
    return {c: getattr(e, c) for c in campos}
