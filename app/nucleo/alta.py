"""Alta por código de invitación.

Quien no tiene acceso y manda un código válido queda atado a él: se crea su usuario (sin
acceso todavía) con una solicitud pendiente, y responde las preguntas fijas del perfil, sin
IA. Al completarlas, la solicitud se aprueba sola (origen "codigo") y queda habilitado.
Tiene 7 días para terminar; después se borra lo que cargó y el código queda gastado.

Sin código: un mensaje fijo, sin IA, y no se guarda nada. Los códigos equivocados se cuentan
por número, con el teléfono en HMAC: después de 5 en 24 horas ningún código sirve, sin
avisar del bloqueo.

Preparado para la aprobación del administrador: sería una solicitud de origen "pedido" que
queda pendiente al terminar las preguntas, en vez de aprobarse sola.
"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.infra.config import config
from app.infra.modelos import IntentoAlta, Solicitud, Usuario
from app.nucleo import auditoria, invitaciones, perfil, usuarios
from app.nucleo.acceso import NO_AUTORIZADO
from app.nucleo.contexto import Contexto
from app.nucleo.cuaderno import Cuaderno
from app.nucleo.invitaciones import en_utc

MAX_INTENTOS = 5
HORAS_INTENTOS = 24
DIAS_PARA_TERMINAR = 7

CODIGO_INVALIDO = (
    "🤔 Ese código no sirve: puede estar mal escrito, vencido o ya usado.\nPedile uno nuevo a quien te invitó."
)
BIENVENIDA = "🎉 *¡Hola! Te doy la bienvenida a CampoBot.*"
LISTA = (
    "✅ *¡Listo, {nombre}! Ya podés usar CampoBot.*\n\n"
    "Contame qué hiciste en el campo y lo anoto, o preguntame por lo que anotaste. "
    "También podés mandarme audios.\n\n"
    "Mandá *ayuda* para ver ejemplos."
)
DE_NUEVO = "✅ *¡Hola de nuevo, {nombre}!* Ya podés usar CampoBot otra vez.\n\nMandá *ayuda* para ver ejemplos."
YA_TENES_ACCESO = "👍 Ya tenés acceso a CampoBot: ese código no hace falta.\nMandá *ayuda* para ver ejemplos."
POR_ESCRITO = "✍️ Para terminar el alta respondé por escrito, por favor."


def _ahora() -> datetime:
    return datetime.now(UTC)


def _hash(telefono: str) -> str:
    # En desarrollo, sin CLAVE_HASH, una clave fija (en producción el servidor no arranca sin ella).
    clave = (config.clave_hash or "campobot-desarrollo").encode()
    return hmac.new(clave, telefono.encode(), hashlib.sha256).hexdigest()


def _bloqueado(db: Session, telefono: str, ahora: datetime) -> bool:
    intento = db.get(IntentoAlta, _hash(telefono))
    vigente = intento is not None and en_utc(intento.desde) > ahora - timedelta(hours=HORAS_INTENTOS)
    return vigente and intento is not None and intento.cantidad >= MAX_INTENTOS


def _sumar_intento(db: Session, telefono: str, ahora: datetime) -> None:
    intento = db.get(IntentoAlta, _hash(telefono))
    if intento is None or en_utc(intento.desde) <= ahora - timedelta(hours=HORAS_INTENTOS):
        db.merge(IntentoAlta(telefono_hash=_hash(telefono), desde=ahora, cantidad=1))
    else:
        intento.cantidad += 1
    db.flush()


def _pendiente(db: Session, usuario: Usuario) -> Solicitud | None:
    q = select(Solicitud).where(Solicitud.usuario_id == usuario.id, Solicitud.estado == usuarios.PENDIENTE)
    return db.scalars(q.order_by(Solicitud.id.desc())).first()


def limpiar(db: Session) -> None:
    """Borra las altas que no se terminaron en 7 días y los intentos de más de 24 horas."""
    ahora = _ahora()
    # "fetch": la base decide qué filas borra (SQLite devuelve las fechas sin zona y no se
    # pueden comparar en Python) y la sesión olvida esas mismas.
    db.execute(
        delete(IntentoAlta)
        .where(IntentoAlta.desde <= ahora - timedelta(hours=HORAS_INTENTOS))
        .execution_options(synchronize_session="fetch")
    )
    vencidas = db.scalars(
        select(Solicitud).where(
            Solicitud.estado == usuarios.PENDIENTE, Solicitud.creado <= ahora - timedelta(days=DIAS_PARA_TERMINAR)
        )
    ).all()
    for solicitud in vencidas:
        usuario = db.get(Usuario, solicitud.usuario_id)
        if usuario is not None and not usuario.autorizado and Cuaderno(db, usuario).cantidad() == 0:
            auditoria.registrar(db, auditoria.ALTA_VENCIDA, sobre=usuario.id, solicitud=solicitud.id)
            usuarios.eliminar(db, usuario)  # con la solicitud: no queda nada de la persona
        else:
            # Alguien a quien le habían sacado el acceso y tiene registros: se conservan.
            db.delete(solicitud)
    db.flush()


def en_curso(db: Session, telefono: str) -> Usuario | None:
    """La persona que está respondiendo las preguntas del alta con un código."""
    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono))
    if usuario is None or usuario.autorizado or _pendiente(db, usuario) is None:
        return None
    return usuario


def _aprobar(db: Session, usuario: Usuario, solicitud: Solicitud) -> None:
    solicitud.estado = usuarios.APROBADA
    solicitud.resuelto = _ahora()
    usuario.autorizado = True
    db.flush()
    auditoria.registrar(
        db, auditoria.ALTA, sobre=usuario.id, solicitud=solicitud.id, invitacion=solicitud.invitacion_id or 0
    )


def sin_acceso(db: Session, telefono: str, texto: str, nombre: str | None) -> str:
    """Quien escribe sin acceso: si manda un código válido empieza el alta; si no, el mensaje fijo."""
    codigo = invitaciones.buscar_codigo(texto)
    if codigo is None:
        return NO_AUTORIZADO  # no se guarda nada
    ahora = _ahora()
    invitacion = None if _bloqueado(db, telefono, ahora) else invitaciones.tomar(db, codigo, ahora)
    if invitacion is None:
        _sumar_intento(db, telefono, ahora)
        return CODIGO_INVALIDO

    usuario = db.scalar(select(Usuario).where(Usuario.telefono == telefono)) or usuarios.nuevo(db, telefono, nombre)
    solicitud = Solicitud(
        usuario_id=usuario.id, invitacion_id=invitacion.id, origen=usuarios.POR_CODIGO, estado=usuarios.PENDIENTE
    )
    db.add(solicitud)
    db.flush()
    if perfil.falta(usuario) is None:  # alguien a quien le habían sacado el acceso
        _aprobar(db, usuario, solicitud)
        return DE_NUEVO.format(nombre=_primer_nombre(usuario))
    usuario.pregunta = perfil.falta(usuario)
    return f"{perfil.intro(usuario, BIENVENIDA)}{perfil.PREGUNTAS[usuario.pregunta or 'nombre']}"


def _primer_nombre(usuario: Usuario) -> str:
    return (usuario.nombre_completo or "").split(" ")[0]


def preguntar(ctx: Contexto, respuesta_fija: str | None) -> str:
    """Las preguntas fijas del perfil. Si con esta respuesta se completa un alta por código,
    la solicitud se aprueba y la persona queda habilitada."""
    respuesta = perfil.alta(ctx, respuesta_fija)
    usuario = ctx.usuario
    if usuario.autorizado or perfil.falta(usuario) is not None:
        return respuesta
    solicitud = _pendiente(ctx.db, usuario)
    if solicitud is None:
        return respuesta
    _aprobar(ctx.db, usuario, solicitud)
    return LISTA.format(nombre=_primer_nombre(usuario))
