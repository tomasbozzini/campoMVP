"""Lógica del asistente: recibe el texto de un usuario y devuelve la respuesta.

El bot es un asistente PERSONAL: cada número de WhatsApp tiene su propio cuaderno.
Lo que anota un veterinario en los campos que recorre queda solo en su cuaderno; el dueño
de un campo anota en su propio cuaderno. Los datos nunca se comparten entre personas.
"""

import logging
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import config, llm, precios, senasa, usuarios
from app.consultas import buscar, normalizar_lote, totales
from app.models import BorradoPendiente, Evento, MensajeChat, Usuario, UsoDiario

log = logging.getLogger(__name__)

CATEGORIAS = {"sanidad", "movimiento", "pesada", "reproduccion", "campo"}

AYUDA = """🐄 *Tu asistente de campo*

Contame lo que hacés y yo lo anoto en tu cuaderno. Por ejemplo:
• _Estoy en La Esperanza_
• _Vacuné 20 vacas contra aftosa en el lote 3_
• _En El Ombú hice tacto a 50 vaquillonas_
• _Llovieron 35 mm_

Si algo quedó mal, corregilo o borralo:
• _A esas vaquillonas las vacuné con ivermectina_
• _No eran 20, eran 25_
• _Borrá la lluvia de La Pastora_

Preguntame por lo que anotaste:
• _¿Qué tengo anotado?_
• _¿Qué hice hoy?_
• _¿Qué hice en La Esperanza este mes?_
• _¿Cuántas vacas vacuné esta semana?_

Precios de referencia de fuentes oficiales:
• _¿A cuánto está la soja?_
• _Precio del novillo_

Y si un producto veterinario está registrado en SENASA:
• _¿La ivermectina está aprobada por SENASA?_

También podés mandar audios 🎤
Lo que anotás es solo tuyo: nadie más lo ve.

Comandos:
• *borrar*: deshace lo último que anotaste
• *ayuda*: este mensaje"""

NO_AUTORIZADO = """Hola 👋 Este número todavía no tiene acceso al asistente.
Pedile al administrador que te habilite."""

FUERA_DE_ALCANCE = """Eso no lo puedo responder. Solo puedo:
• Anotar lo que hacés en el campo
• Responder sobre lo que vos anotaste
• Mostrar precios de referencia de granos y hacienda de fuentes oficiales
• Verificar si un producto veterinario está registrado en SENASA

No doy recomendaciones, indicaciones de uso ni precios de medicamentos, y no respondo otros temas. Mandá *ayuda* para ver ejemplos."""

AYUDA_ADMIN = """
Comandos de administrador:
• *autorizar 5492494123456*: le da acceso a ese número
• *quitar 5492494123456*: le saca el acceso (sus registros se conservan)
• *autorizados*: lista de números con acceso"""


def _hoy() -> date:
    return datetime.now(config.ZONA_HORARIA).date()


def es_admin(telefono: str) -> bool:
    return telefono in config.ADMIN_TELEFONOS


def normalizar_telefono(texto: str) -> str | None:
    """Deja el número como lo manda WhatsApp: 549 + característica + número.

    Acepta "+54 9 249 412-3456" o "542494123456" (sin el 9, como lo guarda Meta).
    """
    digitos = re.sub(r"\D", "", texto)
    if digitos.startswith("54") and not digitos.startswith("549") and len(digitos) == 12:
        digitos = "549" + digitos[2:]
    return digitos if 10 <= len(digitos) <= 15 else None


def puede_usar_ia(db: Session, telefono: str) -> bool:
    """Para los audios: no transcribimos nada de números sin acceso."""
    if es_admin(telefono):
        return True
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    return usuario is not None and usuario.autorizado


def _usuario(db: Session, telefono: str, nombre: str | None) -> Usuario | None:
    """El usuario si tiene acceso; None si no. A los números sin acceso no se los guarda."""
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    if usuario is None and es_admin(telefono):
        usuario = Usuario(telefono=telefono, nombre=nombre, autorizado=True)
        db.add(usuario)
        db.flush()
    if usuario is None or not (usuario.autorizado or es_admin(telefono)):
        return None
    if nombre and not usuario.nombre:
        usuario.nombre = nombre
    return usuario


# Contexto de la charla que ve la IA: solo de la misma persona y de los últimos minutos.
HISTORIAL_MENSAJES = 6
HISTORIAL_MINUTOS = 30
HISTORIAL_LARGO = 600  # caracteres por mensaje guardado

SALUDO = "¡Hola! 👋 Contame qué hiciste y lo anoto, o preguntame por lo que tenés anotado. Mandá *ayuda* para ver ejemplos."
GRACIAS = "¡De nada! 👍"

# Preguntas fijas para cuando falta un dato. La IA elige cuáles faltan; el texto es del código.
PREGUNTAS = {
    "que_paso": "¿Qué querés que anote? Contame qué hiciste, por ejemplo: _vacuné 20 vacas en el lote 3_.",
    "establecimiento": "¿En qué establecimiento fue?",
    "cual_registro": "¿Cuál de tus registros? Decime el tipo, la fecha, el lote o el campo. Con *¿qué tengo anotado?* ves la lista.",
    "que_cambiar": "¿Qué querés cambiar de ese registro?",
    "cantidad": "¿Cuántos animales eran?",
    "producto": "¿Qué producto usaste?",
    "fecha": "¿Qué día fue?",
    "que_producto_precio": "¿De qué grano o categoría de hacienda querés el precio? Por ejemplo: _soja_, _novillo_.",
}


def manejar_mensaje(
    db: Session, telefono: str, texto: str, nombre: str | None = None, hoy: date | None = None
) -> str:
    texto = texto.strip()
    usuario = _usuario(db, telefono, nombre)
    if usuario is None:
        return NO_AUTORIZADO
    respuesta = _responder(db, usuario, telefono, texto, hoy or _hoy())
    _guardar_charla(db, usuario, texto, respuesta)
    return respuesta


def _historial(db: Session, usuario: Usuario) -> list[tuple[str, str]]:
    desde = datetime.now(timezone.utc) - timedelta(minutes=HISTORIAL_MINUTOS)
    filas = db.scalars(
        select(MensajeChat)
        .where(MensajeChat.usuario_id == usuario.id, MensajeChat.creado >= desde)
        .order_by(MensajeChat.id.desc()).limit(HISTORIAL_MENSAJES)
    ).all()
    return [(f.rol, f.texto) for f in reversed(filas)]


def _guardar_charla(db: Session, usuario: Usuario, texto: str, respuesta: str) -> None:
    db.add(MensajeChat(usuario_id=usuario.id, rol="usuario", texto=texto[:HISTORIAL_LARGO]))
    db.add(MensajeChat(usuario_id=usuario.id, rol="bot", texto=respuesta[:HISTORIAL_LARGO]))
    # No hace falta guardar más que lo que se usa como contexto.
    viejos = db.scalars(
        select(MensajeChat.id).where(MensajeChat.usuario_id == usuario.id)
        .order_by(MensajeChat.id.desc()).offset(HISTORIAL_MENSAJES * 2)
    ).all()
    if viejos:
        db.execute(delete(MensajeChat).where(MensajeChat.id.in_(viejos)))
    db.flush()


def _responder(db: Session, usuario: Usuario, telefono: str, texto: str, hoy: date) -> str:
    comando = texto.lower().strip(" !.¡")
    if (respuesta := _resolver_borrado_pendiente(db, usuario, comando)) is not None:
        return respuesta
    if es_admin(telefono) and (respuesta := _comando_admin(db, texto)):
        return respuesta
    if comando in ("ayuda", "help", "menu", "menú"):
        return AYUDA + (AYUDA_ADMIN if es_admin(telefono) else "")
    if comando in ("borrar", "deshacer"):
        return _borrar_ultimo(db, usuario)

    if len(texto) > config.MAX_LARGO_MENSAJE:
        return "El mensaje es muy largo. Mandalo en partes más cortas, de a un tema por vez."
    if not consumir_cupo(db, usuario, hoy):
        return "Llegaste al límite de mensajes por hoy. Mañana podés seguir."

    try:
        interpretado = llm.interpretar(texto, hoy, _historial(db, usuario))
    except Exception:
        log.exception("Error interpretando mensaje")
        return "Uy, no pude procesar el mensaje. Probá de nuevo en un ratito."
    if not isinstance(interpretado, dict):
        return FUERA_DE_ALCANCE
    # Un mensaje puede traer varios pedidos ("¿cuánto está la soja y el maíz?", "anotá la
    # lluvia y borrá la cosecha"). Se aceptan también respuestas viejas de una sola acción.
    acciones = interpretado.get("acciones") if isinstance(interpretado.get("acciones"), list) else [interpretado]
    acciones = [a for a in acciones if isinstance(a, dict)][:MAX_ACCIONES]
    return _ejecutar_acciones(db, usuario, texto, acciones, hoy)


MAX_ACCIONES = 6
SEPARADOR = "\n\n"
FUERA_PARCIAL = "Lo demás que pediste no lo puedo responder: no doy recomendaciones ni respondo temas que no sean de tu cuaderno, precios oficiales o SENASA."


def _ejecutar_acciones(db: Session, usuario: Usuario, texto: str, acciones: list[dict], hoy: date) -> str:
    if not acciones:
        return FUERA_DE_ALCANCE
    varias = len(acciones) > 1
    respuestas: list[str] = []
    hubo_fuera = False
    precios_pedidos: list[tuple[str | None, str | None]] = []
    posicion_precios: int | None = None

    for accion in acciones:
        intencion = accion.get("intencion")
        if varias and intencion == "saludo":
            continue  # "hola, ¿cuánto está la soja?": se responde solo lo que pide
        if intencion == "precio" and isinstance(accion.get("precio"), dict):
            # Los precios se juntan en una sola respuesta, para no repetir la fuente.
            pedido = accion["precio"]
            rubro = pedido.get("rubro") if pedido.get("rubro") in ("granos", "hacienda") else None
            producto = _texto(pedido.get("producto"), 40)
            if producto or rubro:
                if posicion_precios is None:
                    posicion_precios = len(respuestas)
                    respuestas.append("")
                precios_pedidos.append((producto, rubro))
                continue
        respuesta = _ejecutar(db, usuario, texto, accion, hoy)
        if respuesta == FUERA_DE_ALCANCE:
            hubo_fuera = True
        else:
            respuestas.append(respuesta)

    if posicion_precios is not None:
        respuestas[posicion_precios] = precios.responder_varios(db, precios_pedidos, hoy)
    if not respuestas:
        if not hubo_fuera and any(a.get("intencion") == "saludo" for a in acciones):
            return SALUDO
        return FUERA_DE_ALCANCE
    if hubo_fuera:
        respuestas.append(FUERA_PARCIAL)
    return SEPARADOR.join(respuestas)


def _ejecutar(db: Session, usuario: Usuario, texto: str, accion: dict, hoy: date) -> str:
    """Ejecuta UNA acción. La IA solo clasifica: ningún texto escrito por ella llega al
    usuario. Todas las respuestas se arman acá con datos de la base y textos fijos, así no
    puede recomendar, inventar ni usarse como chat de uso general."""
    intencion = accion.get("intencion")
    establecimiento = _texto(accion.get("establecimiento"), 120)
    if intencion == "saludo":
        return GRACIAS if accion.get("agradece") is True else SALUDO
    if intencion == "aclarar":
        faltan = [PREGUNTAS[f] for f in accion.get("falta") or [] if f in PREGUNTAS]
        return "\n".join(dict.fromkeys(faltan)) or PREGUNTAS["que_paso"]
    if intencion == "establecimiento" and establecimiento:
        usuario.establecimiento_actual = establecimiento
        return f"📍 Listo. Lo próximo que anotes lo guardo en *{establecimiento}*."
    if intencion == "registrar" and isinstance(accion.get("eventos"), list):
        return _registrar(db, usuario, texto, accion["eventos"], establecimiento, hoy)
    if intencion == "borrar" and isinstance(accion.get("borrado"), dict):
        return _borrar(db, usuario, accion["borrado"])
    if intencion == "corregir" and isinstance(accion.get("correccion"), dict):
        return _corregir(db, usuario, accion["correccion"], hoy)
    if intencion == "consultar" and isinstance(accion.get("consulta"), dict):
        return _consultar(db, usuario, accion["consulta"])
    if intencion == "precio":
        return PREGUNTAS["que_producto_precio"]
    if intencion == "producto_veterinario" and isinstance(accion.get("producto_veterinario"), dict):
        nombre_producto = _texto(accion["producto_veterinario"].get("nombre"), 80)
        if not nombre_producto:
            return "¿Qué producto querés verificar en SENASA? Decime el nombre comercial o el principio activo."
        return senasa.responder(db, nombre_producto)
    return FUERA_DE_ALCANCE


def _comando_admin(db: Session, texto: str) -> str | None:
    if texto.lower() == "autorizados":
        lista = usuarios.autorizados(db)
        if not lista:
            return "Todavía no autorizaste a nadie."
        return "Números con acceso:\n" + "\n".join(
            f"• {u.telefono}" + (f" ({u.nombre})" if u.nombre else "") for u in lista
        )
    m = re.match(r"^(autorizar|quitar)\s+(.+)$", texto, re.IGNORECASE)
    if not m:
        return None
    telefono = normalizar_telefono(m.group(2))
    if telefono is None:
        return "No entendí el número. Escribilo con código de país, ej: *autorizar 5492494123456*"
    if m.group(1).lower() == "autorizar":
        usuarios.autorizar(db, telefono)
        return f"✅ {telefono} ya puede usar el asistente."
    if not usuarios.quitar(db, telefono):
        return f"{telefono} no tenía acceso."
    return f"🚫 Le saqué el acceso a {telefono}. Sus registros se conservan."


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


def clave_establecimiento(nombre: str | None) -> str | None:
    """"Estancia La Esperanza", "la esperanza" y "La Esperanza" son el mismo lugar."""
    if not nombre:
        return None
    texto = unicodedata.normalize("NFKD", nombre.strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    for prefijo in ("estancia ", "establecimiento ", "campo ", "el campo "):
        if texto.startswith(prefijo):
            texto = texto[len(prefijo):]
    return " ".join(texto.split()) or None


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


def _registrar(
    db: Session, usuario: Usuario, texto: str, eventos: list, establecimiento: str | None, hoy: date
) -> str:
    _heredar_contexto(eventos)
    # Si el mensaje nombra un establecimiento, pasa a ser el actual; si no, se usa el último.
    if establecimiento:
        usuario.establecimiento_actual = establecimiento
    establecimiento = establecimiento or usuario.establecimiento_actual
    mensaje_id = str(uuid.uuid4())  # une los eventos del mensaje para poder "borrar" todo junto
    guardados: list[Evento] = []
    for e in eventos:
        if not isinstance(e, dict):
            continue
        categoria = str(e.get("categoria") or "").lower()
        if categoria not in CATEGORIAS:
            continue
        evento = Evento(
            usuario_id=usuario.id,
            establecimiento=establecimiento,
            establecimiento_clave=clave_establecimiento(establecimiento),
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
    donde = f" en 📍 *{establecimiento}*" if establecimiento else " (sin establecimiento)"
    lineas = [f"✅ Anotado{donde}:"] + [f"• {resumen(e)}" for e in guardados]
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


# Cuántos registros recientes se revisan para encontrar el que se quiere corregir.
CORRECCION_ULTIMOS = 20


def _coincide(e: Evento, referencia: dict) -> bool:
    """¿El registro tiene todos los datos con los que el usuario lo identificó?"""
    for clave, valor in referencia.items():
        if valor in (None, ""):
            continue
        texto = str(valor).strip().lower()
        if clave == "cantidad_animales":
            if e.cantidad_animales != _a_int(valor):
                return False
        elif clave == "categoria_animal":
            if not e.categoria_animal or _singular(texto) not in e.categoria_animal.lower():
                return False
        elif clave in ("lote", "lote_destino"):
            if getattr(e, clave) != normalizar_lote(valor):
                return False
        elif clave == "establecimiento":
            if e.establecimiento_clave != clave_establecimiento(str(valor)):
                return False
        elif clave in ("tipo", "caravana"):
            if (getattr(e, clave) or "").lower() != texto:
                return False
        elif clave == "producto":
            if texto not in (e.producto or "").lower():
                return False
        elif clave == "categoria":
            if e.categoria != texto:
                return False
        elif clave in ("desde", "hasta"):
            try:
                limite = date.fromisoformat(texto)
            except ValueError:
                continue
            if (clave == "desde" and e.fecha_evento < limite) or (clave == "hasta" and e.fecha_evento > limite):
                return False
        elif clave == "fecha_evento":
            try:
                if e.fecha_evento != date.fromisoformat(texto):
                    return False
            except ValueError:
                pass
        # el resto de las claves (descripcion, confianza...) no sirve para identificar
    return True


def _corregir(db: Session, usuario: Usuario, correccion: dict, hoy: date) -> str:
    referencia = correccion.get("referencia") if isinstance(correccion.get("referencia"), dict) else {}
    cambios = correccion.get("cambios") if isinstance(correccion.get("cambios"), dict) else {}
    recientes = db.scalars(
        select(Evento).where(Evento.usuario_id == usuario.id)
        .order_by(Evento.id.desc()).limit(CORRECCION_ULTIMOS)
    ).all()
    evento = next((e for e in recientes if _coincide(e, referencia)), None)
    if evento is None:
        return (
            "No encontré cuál de tus registros querés corregir 🤔. "
            "Si es el último, mandá *borrar* y anotalo de nuevo completo."
        )

    antes = resumen(evento)
    aplicados = 0
    for clave, valor in cambios.items():
        if clave == "establecimiento":
            nombre = _texto(valor, 120)
            if nombre:
                evento.establecimiento = nombre
                evento.establecimiento_clave = clave_establecimiento(nombre)
                aplicados += 1
            continue
        if clave not in _CORREGIBLES or valor in (None, ""):
            continue
        setattr(evento, clave, _CORREGIBLES[clave](valor, hoy))
        aplicados += 1
    if not aplicados:
        return "No entendí qué querés cambiar. Probá con algo como: _eran 30, no 20_"

    db.flush()
    donde = f" · 📍 {evento.establecimiento}" if evento.establecimiento else ""
    return f"✏️ Corregido:\nAntes: {antes}\nAhora: {resumen(evento)}{donde}\n\n_Si algo está mal, mandá *borrar*._"


# Qué se puede corregir y cómo se limpia cada valor (igual que al registrar).
_CORREGIBLES = {
    "tipo": lambda v, hoy: (_texto(v, 30) or "otro").lower(),
    "descripcion": lambda v, hoy: _texto(v, 500),
    "producto": lambda v, hoy: _texto(v, 120),
    "dosis": lambda v, hoy: _texto(v, 60),
    "cantidad_animales": lambda v, hoy: _a_int(v),
    "categoria_animal": lambda v, hoy: (_texto(v, 40) or "").lower() or None,
    "caravana": lambda v, hoy: _texto(v, 40),
    "lote": lambda v, hoy: normalizar_lote(v),
    "lote_destino": lambda v, hoy: normalizar_lote(v),
    "valor": lambda v, hoy: _a_float(v),
    "unidad": lambda v, hoy: _texto(v, 20),
    "fecha_evento": lambda v, hoy: _a_fecha(v, hoy),
}


# Cuántos registros se revisan para encontrar lo que se quiere borrar.
BORRADO_ULTIMOS = 5000
MAX_REFERENCIAS_BORRADO = 10


# Más de esta cantidad de registros de una vez pide confirmación con "sí".
CONFIRMAR_DESDE = 4
CONFIRMAR_MINUTOS = 10
SI = {"si", "sí", "dale", "confirmo", "confirmar", "ok", "si, borralos", "sí, borralos", "si borralos", "sí borralos"}
NO = {"no", "cancelar", "cancela", "cancelá", "no, cancelar"}


def _borrar(db: Session, usuario: Usuario, borrado: dict) -> str:
    """Borra registros que la persona describe ("la lluvia de La Pastora", "todo lo de la lista").

    Cada descripción tiene que señalar UN solo registro. Si coincide con varios, no se
    borra nada de esa descripción y se muestran las opciones para que precise, salvo
    que haya pedido explícitamente borrar todos ("todas las lluvias de La Pastora").
    Si en total se van a borrar muchos registros, se pide confirmación antes.
    """
    referencias = borrado.get("registros")
    if not isinstance(referencias, list) or not referencias:
        return _borrar_ultimo(db, usuario)
    recientes = db.scalars(
        select(Evento).where(Evento.usuario_id == usuario.id)
        .order_by(Evento.id.desc()).limit(BORRADO_ULTIMOS)
    ).all()

    a_borrar: dict[int, Evento] = {}
    avisos: list[str] = []
    for ref in referencias[:MAX_REFERENCIAS_BORRADO]:
        if not isinstance(ref, dict):
            continue
        todos = ref.get("todos") is True
        filtro = {k: v for k, v in ref.items() if k != "todos"}
        hay_filtro = any(v not in (None, "") for v in filtro.values())
        if not hay_filtro and not todos:
            avisos.append("Una de las cosas que pediste borrar no la pude identificar.")
            continue
        # Sin filtro y con "todos": es todo el cuaderno (siempre pide confirmación).
        coinciden = [e for e in recientes if _coincide(e, filtro)] if hay_filtro else list(recientes)
        if not coinciden:
            avisos.append(f"No encontré: {_describir(filtro)}." if hay_filtro else "No tenés nada anotado.")
        elif len(coinciden) > 1 and not todos:
            opciones = "\n".join(f"   • {_linea(e)}" for e in coinciden[:8])
            mas = f"\n   _...y {len(coinciden) - 8} más_" if len(coinciden) > 8 else ""
            avisos.append(
                f"Hay {len(coinciden)} registros que coinciden con {_describir(filtro)} y no borré ninguno:\n"
                f"{opciones}{mas}\n   Decime cuál (con la fecha, el lote o el establecimiento), "
                "o pedí borrar *todos*."
            )
        else:
            a_borrar.update({e.id: e for e in coinciden})

    lineas = []
    if len(a_borrar) >= CONFIRMAR_DESDE:
        db.merge(BorradoPendiente(usuario_id=usuario.id, ids=list(a_borrar), creado=datetime.now(timezone.utc)))
        lista = list(a_borrar.values())
        lineas.append(f"⚠️ Voy a borrar *{len(lista)} registros*:")
        lineas += [f"• {_linea(e)}" for e in lista[:10]]
        if len(lista) > 10:
            lineas.append(f"_...y {len(lista) - 10} más_")
        lineas.append("\n¿Confirmás? Respondé *sí* para borrarlos o *no* para cancelar. Esto no se puede deshacer.")
    elif a_borrar:
        lineas.append("🗑️ Borré:")
        lineas += [f"• {_linea(e)}" for e in a_borrar.values()]
        db.execute(delete(Evento).where(Evento.id.in_(list(a_borrar)), Evento.usuario_id == usuario.id))
    if avisos:
        if lineas:
            lineas.append("")
        lineas += avisos
    return "\n".join(lineas) or "No entendí qué querés borrar."


def _resolver_borrado_pendiente(db: Session, usuario: Usuario, comando: str) -> str | None:
    """Si hay un borrado esperando confirmación: "sí" lo hace, "no" lo cancela, y
    cualquier otro mensaje lo descarta (y sigue el flujo normal)."""
    pendiente = db.get(BorradoPendiente, usuario.id)
    if pendiente is None:
        return None
    db.delete(pendiente)
    db.flush()
    creado = pendiente.creado if pendiente.creado.tzinfo else pendiente.creado.replace(tzinfo=timezone.utc)
    vigente = datetime.now(timezone.utc) - creado <= timedelta(minutes=CONFIRMAR_MINUTOS)
    if comando in NO:
        return "Listo, no borré nada."
    if comando not in SI:
        return None
    if not vigente:
        return "Pasó mucho tiempo desde que lo pediste y no borré nada. Si querés, pedilo de nuevo."
    resultado = db.execute(
        delete(Evento).where(Evento.id.in_(pendiente.ids), Evento.usuario_id == usuario.id)
    )
    return f"🗑️ Listo, borré {resultado.rowcount} registros."


def _linea(e: Evento) -> str:
    return resumen(e) + (f" · 📍 {e.establecimiento}" if e.establecimiento else "")


def _describir(filtro: dict) -> str:
    """Texto armado por el código (no por la IA) para describir lo que se buscó."""
    partes = []
    if filtro.get("tipo"):
        partes.append(_NOMBRES_TIPO.get(str(filtro["tipo"]).lower(), str(filtro["tipo"]).capitalize()))
    if filtro.get("cantidad_animales") is not None and _a_int(filtro["cantidad_animales"]):
        partes.append(str(_a_int(filtro["cantidad_animales"])))
    if filtro.get("categoria_animal"):
        partes.append(_texto(filtro["categoria_animal"], 40))
    if lote := normalizar_lote(filtro.get("lote")):
        partes.append(f"lote {lote}")
    if filtro.get("establecimiento"):
        partes.append(f"en {_texto(filtro['establecimiento'], 60)}")
    return "_" + (" ".join(p for p in partes if p) or "eso") + "_"


def _borrar_ultimo(db: Session, usuario: Usuario) -> str:
    ultimo = db.scalar(
        select(Evento)
        .where(Evento.usuario_id == usuario.id)
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


MAX_LINEAS_CONSULTA = 25


def _consultar(db: Session, usuario: Usuario, filtros: dict) -> str:
    filtros = {**filtros, "establecimiento": clave_establecimiento(_texto(filtros.get("establecimiento"), 120))}
    eventos = buscar(db, usuario.id, filtros)
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
    lineas += [f"• {_linea(e)}" for e in eventos[:MAX_LINEAS_CONSULTA]]
    if len(eventos) > MAX_LINEAS_CONSULTA:
        lineas.append(f"_...y {len(eventos) - MAX_LINEAS_CONSULTA} más. Pedí un período, lote o establecimiento más chico para verlos._")
    return "\n".join(lineas)
