"""Sesiones: un trabajo en un lote, una manga o una tarea, con apertura, cierre y resumen.

Reglas (docs/arquitectura.md, decisiones de producto "Sesiones" y "Campo actual"):

- Una abierta por persona. Al abrir otra, la anterior se cierra con su resumen.
- Un registro que no nombra campo va a la sesión y hereda su campo y su lote (la lluvia no
  hereda el lote: es del campo). Uno que nombra otro establecimiento queda fuera, con
  aviso, y los siguientes sin campo siguen yendo a la sesión.
- Se cierra sola a las 12 horas sin mensajes de la persona (cualquier mensaje cuenta). El
  bot no manda nada por su cuenta: cuando la persona vuelve a escribir se le avisa y se le
  muestra el resumen.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.infra.config import config
from app.infra.modelos import Establecimiento, Evento, Lote, Sesion
from app.nucleo.contexto import Contexto
from app.nucleo.cuaderno import Cuaderno
from app.salidas import whatsapp as formato
from app.salidas.whatsapp import SEPARADOR as LINEA

HORAS_SIN_ACTIVIDAD = 12
MAX_EN_RESUMEN = 15
# Por qué se cerró: la persona lo pidió, abrió otra o pasaron las 12 horas.
PEDIDO, OTRA, TIEMPO = "pedido", "otra", "tiempo"

CERRAR = {"cerrar sesion", "cerrar la sesion", "terminar sesion", "terminar la sesion", "fin de sesion"}

# Lo que un módulo le suma al resumen de una sesión, después de los totales (las cuentas del
# tacto vaca por vaca): nombre -> función que recibe los registros de la sesión y devuelve el
# bloque, o None. Lo registra el módulo al cargarse.
BLOQUES_RESUMEN: dict[str, Callable[[list[Evento]], str | None]] = {}
SIN_SESION = "🤔 No tenés ninguna sesión abierta.\nPara abrir una, decime por ejemplo: _arranco manga en El Retiro_."


def _con_zona(momento: datetime) -> datetime:
    """SQLite devuelve las fechas sin zona: son UTC."""
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def _hora(momento: datetime) -> datetime:
    return _con_zona(momento).astimezone(config.zona_horaria)


def nombre(sesion: Sesion) -> str:
    """📍 El Retiro · Lote 3 · Manga"""
    partes = [f"📍 {sesion.establecimiento.nombre}" if sesion.establecimiento else "📍 _sin establecimiento_"]
    if sesion.lote:
        partes.append(f"Lote {sesion.lote.nombre}")
    if sesion.actividad:
        partes.append(sesion.actividad[:1].upper() + sesion.actividad[1:])
    return " · ".join(partes)


def _cuanto(desde: datetime, hasta: datetime) -> str:
    minutos = max(0, int((hasta - desde).total_seconds() // 60))
    horas, minutos = divmod(minutos, 60)
    return f"{horas} h {minutos} min" if horas else f"{minutos} min"


def _horario(sesion: Sesion) -> str:
    """🕐 Jue 15/10/2026 08:15 a 12:40 (4 h 25 min)"""
    desde, hasta = _hora(sesion.abierta), _hora(sesion.cerrada or sesion.ultima_actividad)
    fin = (
        hasta.strftime("%H:%M")
        if hasta.date() == desde.date()
        else f"{formato.fecha_corta(hasta.date())} {hasta:%H:%M}"
    )
    return f"🕐 {formato.fecha_corta(desde.date())} {desde:%H:%M} a {fin} ({_cuanto(desde, hasta)})"


def resumen(cuaderno: Cuaderno, sesion: Sesion) -> str:
    """Lo que se anotó en la sesión, con los totales. Las cuentas las hace el código."""
    eventos = cuaderno.registros_de_sesion(sesion)
    cantidad = f"{len(eventos)} registro{'s' if len(eventos) != 1 else ''}"
    partes = [f"⏹️ *SESIÓN CERRADA*\n{nombre(sesion)}\n{_horario(sesion)}\n📋 {cantidad}"]
    if not eventos:
        partes.append("_No anotaste nada en esta sesión._")
        return "\n\n".join(partes)
    if bloque := formato.totales(eventos):
        partes.append(bloque)
    partes += [b for armar in BLOQUES_RESUMEN.values() if (b := armar(eventos))]
    varios_dias = len({e.fecha_evento for e in eventos}) > 1
    partes.append(LINEA)
    partes.append(formato.tarjetas(eventos[:MAX_EN_RESUMEN], lugar=False, fecha=varios_dias))
    if len(eventos) > MAX_EN_RESUMEN:
        partes.append(f"_...y {len(eventos) - MAX_EN_RESUMEN} más. Con *¿qué tengo anotado?* los ves todos._")
    return "\n\n".join(partes)


def cerrar(cuaderno: Cuaderno, sesion: Sesion, cuando: datetime, motivo: str) -> str:
    """Cierra la sesión y devuelve su resumen."""
    sesion.cerrada = cuando
    sesion.motivo_cierre = motivo
    cuaderno.db.flush()
    return resumen(cuaderno, sesion)


def al_escribir(cuaderno: Cuaderno, ahora: datetime) -> str | None:
    """Con cada mensaje de la persona: si la sesión abierta lleva 12 horas sin mensajes, se
    cierra y se devuelve el aviso con su resumen; si no, el mensaje cuenta como actividad."""
    sesion = cuaderno.sesion_abierta()
    if sesion is None:
        return None
    vence = _con_zona(sesion.ultima_actividad) + timedelta(hours=HORAS_SIN_ACTIVIDAD)
    if ahora < vence:
        sesion.ultima_actividad = ahora
        return None
    texto = cerrar(cuaderno, sesion, vence, TIEMPO)
    return f"⏱️ Pasaron {HORAS_SIN_ACTIVIDAD} horas sin mensajes y la sesión se cerró sola.\n\n{texto}"


def abrir(ctx: Contexto, campo: str | None, lote: str | None, actividad: str | None) -> str:
    """Abre una sesión. Sin campo, en el campo actual. Si había otra abierta, se cierra antes."""
    cuaderno, usuario = ctx.cuaderno, ctx.usuario
    previa = ""
    if (abierta := cuaderno.sesion_abierta()) is not None:
        previa = cerrar(cuaderno, abierta, ctx.ahora, OTRA) + f"\n\n{formato.SEPARADOR}\n\n"
    # Nombrar el campo al abrir lo deja como campo actual ("Campo actual" en el plan).
    if campo and (nombrado := cuaderno.establecimiento(campo)):
        usuario.establecimiento_actual = nombrado
    establecimiento = usuario.establecimiento_actual
    sesion = cuaderno.abrir_sesion(establecimiento, cuaderno.lote(lote, establecimiento), actividad, ctx.ahora)
    donde = "en esta sesión" + (f", en el lote {sesion.lote.nombre}" if sesion.lote else "")
    return (
        f"{previa}▶️ *SESIÓN ABIERTA*\n{nombre(sesion)}\n\n"
        f"Lo que anotes sin decir el campo queda {donde}.\n"
        "Cuando termines, decime _terminamos_ o mandá *cerrar sesión*."
    )


def cerrar_pedido(ctx: Contexto) -> str:
    """La persona avisa que terminó ("terminamos", "cerrar sesión")."""
    sesion = ctx.cuaderno.sesion_abierta()
    if sesion is None:
        return SIN_SESION
    return cerrar(ctx.cuaderno, sesion, ctx.ahora, PEDIDO)


@dataclass(frozen=True)
class Destino:
    """Dónde va un registro: su campo, su sesión, el lote que hereda y un aviso, si queda
    fuera de la sesión."""

    establecimiento: Establecimiento | None
    sesion: Sesion | None = None
    lote: Lote | None = None
    aviso: str | None = None

    def lote_para(self, tipo: str | None) -> Lote | None:
        """El lote que hereda un registro que no dice el suyo. La lluvia no hereda: es del campo."""
        return None if tipo == "lluvia" else self.lote


def destino(ctx: Contexto, nombrado: Establecimiento | None) -> Destino:
    """Dónde van los registros de un mensaje. `nombrado`: el campo que nombra el mensaje."""
    sesion = ctx.cuaderno.sesion_abierta()
    if sesion is None:
        return Destino(ctx.usuario.establecimiento_actual)
    if nombrado is None or nombrado.id == sesion.establecimiento_id:
        return Destino(sesion.establecimiento, sesion, sesion.lote)
    return Destino(
        nombrado,
        aviso=(
            f"⚠️ Quedó en *{nombrado.nombre}*, fuera de la sesión abierta ({nombre(sesion)}).\n"
            "_Lo que anotes sin decir el campo sigue yendo a la sesión._"
        ),
    )


def aviso_otro_campo(ctx: Contexto, campo: Establecimiento) -> str | None:
    """Para "estoy en El Ombú" con una sesión abierta en otro campo: lo próximo va a la sesión,
    y cómo cerrarla."""
    sesion = ctx.cuaderno.sesion_abierta()
    if sesion is None or sesion.establecimiento_id == campo.id:
        return None
    donde = f" en {sesion.establecimiento.nombre}" if sesion.establecimiento else ""
    return (
        f"⚠️ Tenés abierta una sesión ({nombre(sesion)}): lo que anotes sin decir el campo va ahí.\n"
        f"Si ya terminaste{donde}, decí _terminamos_ y te paso el resumen."
    )
