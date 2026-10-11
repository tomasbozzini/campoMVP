"""Lógica del asistente: recibe el texto de un usuario y devuelve la respuesta."""

import logging
import re
import secrets
import uuid
from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import config, llm, precios, senasa
from app.consultas import buscar, normalizar_lote, totales
from app.models import Campo, Evento, Usuario, UsoDiario

log = logging.getLogger(__name__)

CATEGORIAS = {"sanidad", "movimiento", "pesada", "reproduccion", "campo"}

AYUDA = """🐄 *Asistente de campo*

Contame lo que pasa y yo lo anoto. Por ejemplo:
• _Hoy vacunamos 20 vacas contra aftosa en el lote 3_
• _Ayer nacieron 4 terneros en el potrero grande_
• _Llovieron 35 mm_
• _Pasamos 50 vaquillonas del lote 2 al 5_

Preguntame por lo que anotaron:
• _¿Cuántas vacas se vacunaron este mes?_
• _¿Qué se le hizo al lote 3?_
• _¿Cuánto llovió en septiembre?_

Precios de referencia de fuentes oficiales:
• _¿A cuánto está la soja?_
• _Precio del novillo_

Y si un producto veterinario está registrado en SENASA:
• _¿La ivermectina está aprobada por SENASA?_

También podés mandar audios 🎤

Comandos:
• *borrar*: deshace lo último que anotaste
• *codigo*: código para sumar gente a tu campo
• *ayuda*: este mensaje"""

BIENVENIDA = """👋 ¡Hola! Soy un asistente para registrar lo que pasa en el campo.

Para empezar:
• Si sos el dueño o encargado, mandá: *crear campo* y el nombre. Ej: _crear campo La Esperanza_
• Si te pasaron un código, mandá: *unirme* y el código. Ej: _unirme K7P2QX_"""

FUERA_DE_ALCANCE = """Eso no lo puedo responder. Solo puedo:
• Anotar lo que pasa en tu campo
• Responder sobre lo que ustedes registraron
• Mostrar precios de referencia de granos y hacienda de fuentes oficiales
• Verificar si un producto veterinario está registrado en SENASA

No doy recomendaciones, indicaciones de uso ni precios de medicamentos, y no respondo otros temas. Mandá *ayuda* para ver ejemplos."""

_ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I para no confundir


def _hoy() -> date:
    return datetime.now(config.ZONA_HORARIA).date()


def _nuevo_codigo(db: Session) -> str:
    while True:
        codigo = "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(6))
        if not db.scalar(select(Campo).where(Campo.codigo_invitacion == codigo)):
            return codigo


def _usuario(db: Session, telefono: str, nombre: str | None) -> Usuario:
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    if usuario is None:
        usuario = Usuario(telefono=telefono, nombre=nombre)
        db.add(usuario)
        db.flush()
    elif nombre and not usuario.nombre:
        usuario.nombre = nombre
    return usuario


def manejar_mensaje(
    db: Session, telefono: str, texto: str, nombre: str | None = None, hoy: date | None = None
) -> str:
    hoy = hoy or _hoy()
    texto = texto.strip()
    usuario = _usuario(db, telefono, nombre)
    comando = texto.lower()

    if m := re.match(r"^crear\s+campo\s+(.+)$", texto, re.IGNORECASE):
        return _crear_campo(db, usuario, m.group(1).strip())
    if m := re.match(r"^unirme\s+([a-z0-9]+)$", texto, re.IGNORECASE):
        return _unirse(db, usuario, m.group(1).upper())

    if usuario.campo is None:
        return BIENVENIDA

    if comando in ("ayuda", "help", "menu", "menú", "hola"):
        return AYUDA
    if comando in ("codigo", "código", "invitar"):
        return (
            f"Para sumar a alguien a *{usuario.campo.nombre}*, que le mande a este número:\n\n"
            f"unirme {usuario.campo.codigo_invitacion}"
        )
    if comando in ("borrar", "deshacer"):
        return _borrar_ultimo(db, usuario)

    if len(texto) > config.MAX_LARGO_MENSAJE:
        return "El mensaje es muy largo. Mandalo en partes más cortas, de a un tema por vez."
    if not consumir_cupo(db, usuario, hoy):
        return "Llegaste al límite de mensajes por hoy. Mañana podés seguir."

    try:
        interpretado = llm.interpretar(texto, hoy)
    except Exception:
        log.exception("Error interpretando mensaje")
        return "Uy, no pude procesar el mensaje. Probá de nuevo en un ratito."
    if not isinstance(interpretado, dict):
        return FUERA_DE_ALCANCE

    # La IA solo clasifica. Ningún texto escrito por ella llega al usuario: todas las
    # respuestas se arman acá con datos de la base, así no puede recomendar, inventar
    # ni usarse como chat de uso general.
    intencion = interpretado.get("intencion")
    if intencion == "registrar" and isinstance(interpretado.get("eventos"), list):
        return _registrar(db, usuario, texto, interpretado["eventos"], hoy)
    if intencion == "consultar" and isinstance(interpretado.get("consulta"), dict):
        return _consultar(db, usuario, interpretado["consulta"])
    if intencion == "precio" and isinstance(interpretado.get("precio"), dict):
        pedido = interpretado["precio"]
        rubro = pedido.get("rubro") if pedido.get("rubro") in ("granos", "hacienda") else None
        producto = _texto(pedido.get("producto"), 40)
        if not producto and not rubro:
            return FUERA_DE_ALCANCE
        return precios.responder(db, producto, rubro, hoy)
    if intencion == "producto_veterinario" and isinstance(interpretado.get("producto_veterinario"), dict):
        nombre = _texto(interpretado["producto_veterinario"].get("nombre"), 80)
        if not nombre:
            return FUERA_DE_ALCANCE
        return senasa.responder(db, nombre)
    return FUERA_DE_ALCANCE


def puede_usar_ia(db: Session, telefono: str) -> bool:
    """Para los audios: no transcribimos nada de números que no están en un campo."""
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    return usuario is not None and usuario.campo_id is not None


def consumir_cupo(db: Session, usuario: Usuario, hoy: date) -> bool:
    uso = db.scalar(select(UsoDiario).where(UsoDiario.usuario_id == usuario.id, UsoDiario.fecha == hoy))
    if uso is None:
        uso = UsoDiario(usuario_id=usuario.id, fecha=hoy, cantidad=0)
        db.add(uso)
    if uso.cantidad >= config.LIMITE_DIARIO_IA:
        return False
    uso.cantidad += 1
    db.flush()
    return True


def _crear_campo(db: Session, usuario: Usuario, nombre: str) -> str:
    if usuario.campo is not None:
        return (
            f"Ya estás en el campo *{usuario.campo.nombre}*. "
            "Por ahora cada número puede estar en un solo campo."
        )
    campo = Campo(nombre=nombre[:120], codigo_invitacion=_nuevo_codigo(db))
    db.add(campo)
    db.flush()
    usuario.campo_id = campo.id
    usuario.rol = "admin"
    db.flush()
    db.refresh(usuario)
    return (
        f"✅ Listo, creé el campo *{campo.nombre}*.\n\n"
        f"Para sumar a tu gente, que le manden a este número:\n\nunirme {campo.codigo_invitacion}\n\n"
        + AYUDA
    )


def _unirse(db: Session, usuario: Usuario, codigo: str) -> str:
    campo = db.scalar(select(Campo).where(Campo.codigo_invitacion == codigo))
    if campo is None:
        return "No encontré ningún campo con ese código. Revisalo y probá de nuevo."
    if usuario.campo_id == campo.id:
        return f"Ya estás en *{campo.nombre}* 👍"
    if usuario.campo_id is not None:
        return (
            f"Ya estás en el campo *{usuario.campo.nombre}*. "
            "Por ahora cada número puede estar en un solo campo."
        )
    usuario.campo_id = campo.id
    usuario.rol = "miembro"
    db.flush()
    db.refresh(usuario)
    return f"✅ Te sumaste a *{campo.nombre}*.\n\n" + AYUDA


def _a_int(valor) -> int | None:
    try:
        return int(float(valor)) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _a_float(valor) -> float | None:
    try:
        return float(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _a_fecha(valor, hoy: date) -> date:
    try:
        fecha = date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return hoy
    # Un registro no puede ser del futuro; si el modelo se confundió, usamos hoy.
    return min(fecha, hoy)


def _texto(valor, largo: int) -> str | None:
    if valor is None or str(valor).strip() == "":
        return None
    return str(valor).strip()[:largo]


def _distintos(eventos: list, clave: str, normalizar=None) -> set:
    valores = set()
    for e in eventos:
        if not isinstance(e, dict):
            continue
        valor = e.get(clave)
        valor = normalizar(valor) if normalizar else ((_texto(valor, 40) or "").lower() or None)
        if valor:
            valores.add(valor)
    return valores


def _heredar_contexto(eventos: list) -> None:
    """Completa el lote y la categoría de animal que el mensaje menciona una sola vez.

    "ayer nacieron 4 terneros en el lote 5 y murió 1" llega como dos eventos, y el
    segundo viene sin lote ni categoría. Si en todo el mensaje hay un único lote y una
    única categoría, son los que corresponden. Si hay más de uno, no adivinamos.
    """
    if len(eventos) < 2:
        return
    lotes = _distintos(eventos, "lote", normalizar_lote)
    categorias = _distintos(eventos, "categoria_animal")
    lote = next(iter(lotes)) if len(lotes) == 1 else None
    categoria = next(iter(categorias)) if len(categorias) == 1 else None
    if lote is None and categoria is None:
        return
    for e in eventos:
        if not isinstance(e, dict):
            continue
        # Solo heredan los eventos que hablan de animales: una lluvia no pasa a ser
        # "del lote 5" porque en el mismo mensaje se haya nombrado un lote.
        if not (e.get("cantidad_animales") or e.get("caravana")):
            continue
        sin_lote = not normalizar_lote(e.get("lote")) and not normalizar_lote(e.get("lote_destino"))
        if lote and sin_lote:
            e["lote"] = lote
        if categoria and not (_texto(e.get("categoria_animal"), 40) or ""):
            e["categoria_animal"] = categoria


def _registrar(db: Session, usuario: Usuario, texto: str, eventos: list, hoy: date) -> str:
    _heredar_contexto(eventos)
    mensaje_id = str(uuid.uuid4())  # une los eventos del mensaje para poder "borrar" todo junto
    guardados: list[Evento] = []
    for e in eventos:
        if not isinstance(e, dict):
            continue
        categoria = str(e.get("categoria") or "").lower()
        if categoria not in CATEGORIAS:
            continue
        evento = Evento(
            campo_id=usuario.campo_id,
            usuario_id=usuario.id,
            categoria=categoria,
            tipo=(_texto(e.get("tipo"), 30) or "otro").lower(),
            descripcion=_texto(e.get("descripcion"), 500),
            producto=_texto(e.get("producto"), 120),
            dosis=_texto(e.get("dosis"), 60),
            cantidad_animales=_a_int(e.get("cantidad_animales")),
            categoria_animal=(_texto(e.get("categoria_animal"), 40) or "").lower() or None,
            caravana=_texto(e.get("caravana"), 40),
            lote=normalizar_lote(e.get("lote")),
            lote_destino=normalizar_lote(e.get("lote_destino")),
            valor=_a_float(e.get("valor")),
            unidad=_texto(e.get("unidad"), 20),
            fecha_evento=_a_fecha(e.get("fecha_evento"), hoy),
            confianza=_texto(e.get("confianza"), 10),
            mensaje_original=texto,
            mensaje_id=mensaje_id,
        )
        db.add(evento)
        guardados.append(evento)

    if not guardados:
        return (
            "No me quedó claro qué querés anotar 🤔. Probá con algo como: "
            "_hoy vacunamos 20 vacas en el lote 3_"
        )

    db.flush()
    lineas = ["✅ Anotado:"] + [f"• {resumen(e)}" for e in guardados]
    if any(e.confianza == "baja" for e in guardados):
        lineas.append("\n⚠️ No estoy seguro de haber entendido bien. Si algo está mal, mandá *borrar* y repetilo.")
    else:
        lineas.append("\n_Si algo está mal, mandá *borrar*._")
    return "\n".join(lineas)


def _singular(palabra: str) -> str:
    """"vacas" -> "vaca", "animales" -> "animal". Alcanza para las categorías que usamos."""
    if palabra.endswith("es") and len(palabra) > 3:
        return palabra[:-2]
    if palabra.endswith("s") and len(palabra) > 2:
        return palabra[:-1]
    return palabra


_NOMBRES_TIPO = {
    "vacunacion": "Vacunación",
    "desparasitacion": "Desparasitación",
    "inseminacion": "Inseminación",
    "paricion": "Parición",
    "fumigacion": "Fumigación",
    "fertilizacion": "Fertilización",
}


def resumen(e: Evento) -> str:
    partes = [_NOMBRES_TIPO.get(e.tipo, e.tipo.capitalize())]
    if e.producto:
        partes[0] += f" ({e.producto})"
    if e.cantidad_animales:
        nombre = e.categoria_animal or "animales"
        partes.append(f"{e.cantidad_animales} {_singular(nombre) if e.cantidad_animales == 1 else nombre}")
    elif e.categoria_animal:
        partes.append(e.categoria_animal)
    if e.caravana:
        partes.append(f"caravana {e.caravana}")
    if e.lote and e.lote_destino:
        partes.append(f"lote {e.lote} → {e.lote_destino}")
    elif e.lote_destino:
        partes.append(f"→ lote {e.lote_destino}")
    elif e.lote:
        partes.append(f"lote {e.lote}")
    if e.dosis:
        partes.append(e.dosis)
    if e.valor is not None:
        valor = int(e.valor) if float(e.valor).is_integer() else e.valor
        partes.append(f"{valor} {e.unidad or ''}".strip())
    partes.append(e.fecha_evento.strftime("%d/%m/%Y"))
    return " · ".join(partes)


def _borrar_ultimo(db: Session, usuario: Usuario) -> str:
    ultimo = db.scalar(
        select(Evento)
        .where(Evento.usuario_id == usuario.id, Evento.campo_id == usuario.campo_id)
        .order_by(Evento.id.desc())
        .limit(1)
    )
    if ultimo is None:
        return "No tenés nada anotado para borrar."
    if ultimo.mensaje_id is None:
        # Registros anteriores a la columna: sin id no hay forma de agruparlos, y un
        # "mensaje_id IS NULL" borraría todos los viejos de una.
        borrados = [ultimo]
    else:
        # Por mensaje_id y no por fecha: dos mensajes seguidos pueden caer en el mismo
        # timestamp (en Windows el reloj salta cada ~15 ms) y se borraban los dos.
        borrados = db.scalars(
            select(Evento).where(
                Evento.usuario_id == usuario.id, Evento.mensaje_id == ultimo.mensaje_id
            )
        ).all()
    lineas = [f"• {resumen(e)}" for e in borrados]
    db.execute(delete(Evento).where(Evento.id.in_([e.id for e in borrados])))
    return "🗑️ Borré:\n" + "\n".join(lineas)


MAX_LINEAS_CONSULTA = 15


def _consultar(db: Session, usuario: Usuario, filtros: dict) -> str:
    eventos = buscar(db, usuario.campo_id, filtros)
    if not eventos:
        return "No encontré registros para esa consulta."

    lineas = [f"📋 *{len(eventos)} registro{'s' if len(eventos) != 1 else ''}*"]
    animales, valores = totales(eventos)
    for tipo, cantidad in animales.items():
        lineas.append(f"Total {_NOMBRES_TIPO.get(tipo, tipo.capitalize()).lower()}: *{cantidad} animales*")
    for (tipo, unidad), suma in valores.items():
        suma = int(suma) if float(suma).is_integer() else round(suma, 2)
        lineas.append(f"Total {_NOMBRES_TIPO.get(tipo, tipo.capitalize()).lower()}: *{suma} {unidad}*")
    lineas.append("")
    lineas += [f"• {resumen(e)}" for e in eventos[:MAX_LINEAS_CONSULTA]]
    if len(eventos) > MAX_LINEAS_CONSULTA:
        lineas.append(f"_...y {len(eventos) - MAX_LINEAS_CONSULTA} más. Pedí un período o lote más chico para verlos._")
    return "\n".join(lineas)
