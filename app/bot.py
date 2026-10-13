"""Lógica del asistente: recibe el texto de un usuario y devuelve la respuesta.

El bot es un asistente PERSONAL: cada número de WhatsApp tiene su propio cuaderno.
Lo que anota un veterinario en los campos que recorre queda solo en su cuaderno; el dueño
de un campo anota en su propio cuaderno. Los datos nunca se comparten entre personas.
"""

import logging
import re
import unicodedata
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import formato, llm, precios, senasa, usuarios
from app.consultas import buscar, normalizar_lote, totales
from app.formato import SEPARADOR as LINEA
from app.infra.config import config
from app.infra.modelos import BorradoPendiente, Evento, MensajeChat, UsoDiario, Usuario

log = logging.getLogger(__name__)

CATEGORIAS = {"sanidad", "movimiento", "pesada", "reproduccion", "campo"}

AYUDA = """🐄 *TU ASISTENTE DE CAMPO*
_Tu cuaderno de trabajo, por WhatsApp._

✍️ *Anotar*
      › Estoy en La Esperanza
      › Vacuné 20 vacas contra aftosa en el lote 3
      › En El Ombú hice tacto a 50 vaquillonas
      › Llovieron 35 mm

✏️ *Corregir o borrar*
      › A esas vaquillonas les di ivermectina
      › No eran 20, eran 25
      › Borrá la lluvia de La Pastora

🔍 *Consultar*
      › ¿Qué tengo anotado?
      › ¿Qué hice en La Esperanza este mes?
      › ¿Cuántas vacas vacuné esta semana?

💲 *Precios oficiales*
      › ¿A cuánto está la soja y el maíz?
      › Precio del novillo

💊 *Productos en SENASA*
      › ¿La ivermectina está aprobada?

────────────
🎤 También podés mandar audios.
🔒 Lo que anotás es solo tuyo.

*borrar* → deshace lo último que anotaste
*privacidad* → cómo se usan tus datos
*borrar mis datos* → elimina todo lo tuyo
*ayuda* → muestra este menú"""

NO_AUTORIZADO = """👋 *¡Hola!*

Este número todavía no tiene acceso al asistente.
Pedile al administrador que te habilite."""

FUERA_DE_ALCANCE = """🚫 *Eso no lo puedo responder*

Puedo ayudarte con:
      ✍️ Anotar lo que hacés en el campo
      🔍 Consultar lo que anotaste
      💲 Precios oficiales de granos y hacienda
      💊 Verificar productos en SENASA

_No doy recomendaciones, indicaciones de uso ni precios de medicamentos._
Mandá *ayuda* para ver ejemplos."""

AYUDA_ADMIN = """

🔑 *Administrador*
*autorizar 5492494123456* → le da acceso
*quitar 5492494123456* → le saca el acceso
*autorizados* → lista de números con acceso"""


def _hoy() -> date:
    return datetime.now(config.zona_horaria).date()


def es_admin(telefono: str) -> bool:
    return telefono in config.admin_telefonos


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

SALUDO = "👋 *¡Hola!*\n\nContame qué hiciste y lo anoto, o preguntame por lo que tenés anotado.\nMandá *ayuda* para ver ejemplos."
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


def manejar_mensaje(db: Session, telefono: str, texto: str, nombre: str | None = None, hoy: date | None = None) -> str:
    texto = texto.strip()
    usuario = _usuario(db, telefono, nombre)
    if usuario is None:
        return NO_AUTORIZADO
    comando = _comando(texto)
    if comando in PEDIR_BORRAR_DATOS:
        return _pedir_borrar_datos(db, usuario)
    if comando == CONFIRMAR_BORRAR_DATOS:
        # Después de esto no se guarda nada más de esta persona, ni siquiera este mensaje.
        return _borrar_datos(db, usuario)
    respuesta = _responder(db, usuario, telefono, texto, hoy or _hoy())
    _guardar_charla(db, usuario, texto, respuesta)
    return respuesta


def _comando(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower().strip(" !.¡¿?"))
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


# Derecho de supresión (Ley 25.326): la persona puede borrar todo lo suyo desde el chat.
PEDIR_BORRAR_DATOS = {"borrar mis datos", "eliminar mis datos", "borrar mi cuenta", "eliminar mi cuenta"}
CONFIRMAR_BORRAR_DATOS = "confirmo borrar mis datos"


def _pedir_borrar_datos(db: Session, usuario: Usuario) -> str:
    registros = len(db.scalars(select(Evento.id).where(Evento.usuario_id == usuario.id)).all())
    return (
        "⚠️ *BORRAR TODOS TUS DATOS*\n\n"
        "Se van a eliminar para siempre:\n"
        f"      › tu cuaderno ({registros} registro{'s' if registros != 1 else ''})\n"
        "      › tus últimos mensajes con el bot\n"
        "      › tu número y tu nombre de perfil\n\n"
        "También perdés el acceso: para volver a usarlo, el administrador te tiene que habilitar de nuevo.\n\n"
        f"{LINEA}\n"
        "Si estás seguro, mandá exactamente:\n*confirmo borrar mis datos*\n\n"
        "_Si no, ignorá este mensaje y no se borra nada._"
    )


def _borrar_datos(db: Session, usuario: Usuario) -> str:
    for modelo in (Evento, MensajeChat, UsoDiario, BorradoPendiente):
        db.execute(delete(modelo).where(modelo.usuario_id == usuario.id))
    db.delete(usuario)
    db.flush()
    log.info("Usuario %s borró todos sus datos", usuario.id)
    return (
        "🗑️ *DATOS BORRADOS*\n\n"
        "Eliminé tu cuaderno, tus mensajes y tu número. No queda nada tuyo guardado.\n"
        "Gracias por haber usado el asistente 👋"
    )


def _privacidad() -> str:
    texto = (
        "🔒 *TUS DATOS*\n\n"
        "      › Guardo tu número y lo que anotás, solo para mostrártelo a vos.\n"
        "      › Nadie más ve tu cuaderno, ni siquiera quien tenga el mismo campo.\n"
        "      › Tus mensajes los interpreta una IA (Groq) y viajan por WhatsApp (Meta).\n"
        "      › No vendo ni comparto tus datos con nadie más.\n\n"
        "*Qué podés hacer*\n"
        "      › Ver todo lo tuyo: _¿qué tengo anotado?_\n"
        "      › Corregir o borrar registros cuando quieras\n"
        "      › Borrar todo, incluido tu número: *borrar mis datos*"
    )
    if config.privacidad_url:
        texto += f"\n\n{LINEA}\n📄 Política completa:\n{config.privacidad_url}"
    return texto


def _historial(db: Session, usuario: Usuario) -> list[tuple[str, str]]:
    desde = datetime.now(UTC) - timedelta(minutes=HISTORIAL_MINUTOS)
    filas = db.scalars(
        select(MensajeChat)
        .where(MensajeChat.usuario_id == usuario.id, MensajeChat.creado >= desde)
        .order_by(MensajeChat.id.desc())
        .limit(HISTORIAL_MENSAJES)
    ).all()
    return [(f.rol, f.texto) for f in reversed(filas)]


def _guardar_charla(db: Session, usuario: Usuario, texto: str, respuesta: str) -> None:
    db.add(MensajeChat(usuario_id=usuario.id, rol="usuario", texto=texto[:HISTORIAL_LARGO]))
    db.add(MensajeChat(usuario_id=usuario.id, rol="bot", texto=respuesta[:HISTORIAL_LARGO]))
    # No hace falta guardar más que lo que se usa como contexto.
    viejos = db.scalars(
        select(MensajeChat.id)
        .where(MensajeChat.usuario_id == usuario.id)
        .order_by(MensajeChat.id.desc())
        .offset(HISTORIAL_MENSAJES * 2)
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
    if comando in ("privacidad", "mis datos", "datos"):
        return _privacidad()

    if len(texto) > config.max_largo_mensaje:
        return "✋ El mensaje es muy largo.\nMandalo en partes más cortas, de a un tema por vez."
    if not consumir_cupo(db, usuario, hoy):
        return "⏳ Llegaste al límite de mensajes por hoy.\nMañana podés seguir."

    try:
        interpretado = llm.interpretar(texto, hoy, _historial(db, usuario))
    except Exception:
        log.exception("Error interpretando mensaje")
        return "😕 Uy, no pude procesar el mensaje.\nProbá de nuevo en un ratito."
    if not isinstance(interpretado, dict):
        return FUERA_DE_ALCANCE
    # Un mensaje puede traer varios pedidos ("¿cuánto está la soja y el maíz?", "anotá la
    # lluvia y borrá la cosecha"). Se aceptan también respuestas viejas de una sola acción.
    crudas = interpretado.get("acciones")
    lista = crudas if isinstance(crudas, list) else [interpretado]
    acciones = [a for a in lista if isinstance(a, dict)][:MAX_ACCIONES]
    return _ejecutar_acciones(db, usuario, texto, acciones, hoy)


MAX_ACCIONES = 6
SEPARADOR = "\n\n━━━━━━━━━━━━━━━\n\n"  # entre pedidos distintos de un mismo mensaje
FUERA_PARCIAL = "🚫 Lo demás que pediste no lo puedo responder.\n_No doy recomendaciones ni respondo temas que no sean de tu cuaderno, precios oficiales o SENASA._"


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
        return "🤔 " + ("\n".join(dict.fromkeys(faltan)) or PREGUNTAS["que_paso"])
    if intencion == "establecimiento" and establecimiento:
        usuario.establecimiento_actual = establecimiento
        return f"📍 *{establecimiento}*\n\nListo, lo próximo que anotes queda guardado acá."
    if intencion == "registrar" and isinstance(accion.get("eventos"), list):
        return _registrar(db, usuario, texto, accion["eventos"], establecimiento, hoy)
    if intencion == "borrar" and isinstance(accion.get("borrado"), dict):
        return _borrar(db, usuario, accion["borrado"])
    if intencion == "corregir" and isinstance(accion.get("correccion"), dict):
        return _corregir(db, usuario, accion["correccion"], hoy)
    if intencion == "consultar" and isinstance(accion.get("consulta"), dict):
        return _consultar(db, usuario, accion["consulta"])
    if intencion == "precio":
        return "🤔 " + PREGUNTAS["que_producto_precio"]
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
    if uso.cantidad >= config.limite_diario_ia:
        return False
    uso.cantidad += 1
    db.flush()
    return True


def clave_establecimiento(nombre: str | None) -> str | None:
    """ "Estancia La Esperanza", "la esperanza" y "La Esperanza" son el mismo lugar."""
    if not nombre:
        return None
    texto = unicodedata.normalize("NFKD", nombre.strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    for prefijo in ("estancia ", "establecimiento ", "campo ", "el campo "):
        if texto.startswith(prefijo):
            texto = texto[len(prefijo) :]
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


def _registrar(db: Session, usuario: Usuario, texto: str, eventos: list, establecimiento: str | None, hoy: date) -> str:
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
        return "🤔 No me quedó claro qué querés anotar.\nProbá con algo como: _vacuné 20 vacas en el lote 3_"

    db.flush()
    donde = f"📍 {establecimiento}" if establecimiento else "📍 _sin establecimiento_"
    cantidad = f"{len(guardados)} registros" if len(guardados) > 1 else "1 registro"
    partes = [f"✅ *ANOTADO*\n{donde} · {cantidad}", formato.tarjetas(guardados, lugar=False)]
    if any(e.confianza == "baja" for e in guardados):
        partes.append(
            f"{LINEA}\n⚠️ No estoy seguro de haber entendido bien.\n_Si algo está mal, corregilo o mandá *borrar*._"
        )
    else:
        partes.append(f"{LINEA}\n_¿Algo mal? Corregilo o mandá *borrar*._")
    return "\n\n".join(partes)


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
            if not e.categoria_animal or formato.singular(texto) not in e.categoria_animal.lower():
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
    referencia = correccion.get("referencia")
    cambios = correccion.get("cambios")
    if not isinstance(referencia, dict):
        referencia = {}
    if not isinstance(cambios, dict):
        cambios = {}
    recientes = db.scalars(
        select(Evento).where(Evento.usuario_id == usuario.id).order_by(Evento.id.desc()).limit(CORRECCION_ULTIMOS)
    ).all()
    evento = next((e for e in recientes if _coincide(e, referencia)), None)
    if evento is None:
        return (
            "🤔 No encontré cuál de tus registros querés corregir.\n"
            "Con *¿qué tengo anotado?* ves la lista, o mandá *borrar* y anotalo de nuevo."
        )

    antes = formato.foto(evento)
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
        return "🤔 No entendí qué querés cambiar.\nProbá con algo como: _eran 30, no 20_"

    db.flush()
    cambios_hechos = formato.cambios(antes, evento)
    if not cambios_hechos:
        return "👌 Ese registro ya tenía esos datos, no cambié nada.\n\n" + formato.tarjeta(evento)
    return "\n\n".join(
        [
            "✏️ *CORREGIDO*",
            "\n".join(cambios_hechos),
            "*Así quedó:*\n" + formato.tarjeta(evento),
            f"{LINEA}\n_¿Algo mal? Corregilo de nuevo o mandá *borrar*._",
        ]
    )


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
        select(Evento).where(Evento.usuario_id == usuario.id).order_by(Evento.id.desc()).limit(BORRADO_ULTIMOS)
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
            avisos.append("🤔 Una de las cosas que pediste borrar no la pude identificar.")
            continue
        # Sin filtro y con "todos": es todo el cuaderno (siempre pide confirmación).
        coinciden = [e for e in recientes if _coincide(e, filtro)] if hay_filtro else list(recientes)
        if not coinciden:
            avisos.append(f"🔍 No encontré: {_describir(filtro)}." if hay_filtro else "📭 No tenés nada anotado.")
        elif len(coinciden) > 1 and not todos:
            opciones = "\n".join(f"      › {formato.linea(e)}" for e in coinciden[:8])
            mas = f"\n      _...y {len(coinciden) - 8} más_" if len(coinciden) > 8 else ""
            avisos.append(
                f"🤔 *Hay {len(coinciden)} registros* que coinciden con {_describir(filtro)}.\n"
                f"No borré ninguno:\n\n{opciones}{mas}\n\n"
                "Decime cuál (con la fecha, el lote o el campo), o pedí borrar *todos*."
            )
        else:
            a_borrar.update({e.id: e for e in coinciden})

    lineas = []
    if len(a_borrar) >= CONFIRMAR_DESDE:
        db.merge(BorradoPendiente(usuario_id=usuario.id, ids=list(a_borrar), creado=datetime.now(UTC)))
        lista = list(a_borrar.values())
        lineas.append(f"⚠️ *VOY A BORRAR {len(lista)} REGISTROS*\n")
        lineas += [f"      › {formato.linea(e)}" for e in lista[:10]]
        if len(lista) > 10:
            lineas.append(f"      _...y {len(lista) - 10} más_")
        lineas.append(
            f"\n{LINEA}\n¿Confirmás? Respondé *sí* para borrarlos o *no* para cancelar.\n_Esto no se puede deshacer._"
        )
    elif a_borrar:
        lineas.append("🗑️ *BORRADO*\n")
        lineas.append(formato.tarjetas(list(a_borrar.values())))
        db.execute(delete(Evento).where(Evento.id.in_(list(a_borrar)), Evento.usuario_id == usuario.id))
    if avisos:
        if lineas:
            lineas.append("")
        lineas += avisos
    return "\n".join(lineas) or "🤔 No entendí qué querés borrar."


def _resolver_borrado_pendiente(db: Session, usuario: Usuario, comando: str) -> str | None:
    """Si hay un borrado esperando confirmación: "sí" lo hace, "no" lo cancela, y
    cualquier otro mensaje lo descarta (y sigue el flujo normal)."""
    pendiente = db.get(BorradoPendiente, usuario.id)
    if pendiente is None:
        return None
    db.delete(pendiente)
    db.flush()
    creado = pendiente.creado if pendiente.creado.tzinfo else pendiente.creado.replace(tzinfo=UTC)
    vigente = datetime.now(UTC) - creado <= timedelta(minutes=CONFIRMAR_MINUTOS)
    if comando in NO:
        return "👌 Listo, no borré nada."
    if comando not in SI:
        return None
    if not vigente:
        return "⏱️ Pasó mucho tiempo desde que lo pediste y no borré nada.\nSi querés, pedilo de nuevo."
    resultado = db.execute(delete(Evento).where(Evento.id.in_(pendiente.ids), Evento.usuario_id == usuario.id))
    borrados = getattr(resultado, "rowcount", 0)
    return f"🗑️ *BORRADO*\n\nListo, borré {borrados} registros."


def _describir(filtro: dict) -> str:
    """Texto armado por el código (no por la IA) para describir lo que se buscó."""
    partes: list[str | None] = []
    if filtro.get("tipo"):
        partes.append(formato.nombre_tipo(str(filtro["tipo"]).lower()))
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
    ultimo = db.scalar(select(Evento).where(Evento.usuario_id == usuario.id).order_by(Evento.id.desc()).limit(1))
    if ultimo is None:
        return "📭 No tenés nada anotado para borrar."
    if ultimo.mensaje_id is None:
        # Registros anteriores a la columna: sin id no hay forma de agruparlos, y un
        # "mensaje_id IS NULL" borraría todos los viejos de una.
        borrados = [ultimo]
    else:
        # Por mensaje_id y no por fecha: dos mensajes seguidos pueden caer en el mismo
        # timestamp (en Windows el reloj salta cada ~15 ms) y se borraban los dos.
        borrados = list(
            db.scalars(
                select(Evento).where(Evento.usuario_id == usuario.id, Evento.mensaje_id == ultimo.mensaje_id)
            ).all()
        )
    texto = formato.tarjetas(list(borrados))
    db.execute(delete(Evento).where(Evento.id.in_([e.id for e in borrados])))
    return "🗑️ *BORRADO*\n\n" + texto


MAX_LINEAS_CONSULTA = 15


def _consultar(db: Session, usuario: Usuario, filtros: dict) -> str:
    nombre_lugar = _texto(filtros.get("establecimiento"), 120)
    filtros = {**filtros, "establecimiento": clave_establecimiento(nombre_lugar)}
    eventos = buscar(db, usuario.id, filtros)
    if not eventos:
        return "🔍 No encontré registros para esa consulta."

    lugares = {e.establecimiento for e in eventos}
    subtitulo = [f"📍 {eventos[0].establecimiento}"] if len(lugares) == 1 and eventos[0].establecimiento else []
    subtitulo.append(f"{len(eventos)} registro{'s' if len(eventos) != 1 else ''}")
    partes = ["📋 *TUS REGISTROS*\n" + " · ".join(subtitulo)]

    animales, valores = totales(eventos)
    if animales or valores:
        filas = [f"      {formato.icono(t)} {formato.nombre_tipo(t)}: *{c}* animales" for t, c in animales.items()]
        filas += [
            f"      {formato.icono(t)} {formato.nombre_tipo(t)}: *{formato.numero(v)} {u}*"
            for (t, u), v in valores.items()
        ]
        partes.append("📊 *Totales*\n" + "\n".join(filas))

    partes.append(LINEA)
    mostrados = eventos[:MAX_LINEAS_CONSULTA]
    # Si todos son del mismo lugar, ya figura arriba: no se repite en cada registro.
    partes.append(formato.por_dia(mostrados, lugar=len(lugares) > 1))
    if len(eventos) > MAX_LINEAS_CONSULTA:
        partes.append(
            f"_...y {len(eventos) - MAX_LINEAS_CONSULTA} más. Pedí un período, lote o campo más chico para verlos._"
        )
    return "\n\n".join(partes)
