"""Pendientes: lo que la persona tiene que hacer más adelante.

Se anotan ("tengo que volver a revisar las vaquillonas el martes"), se consultan ("¿qué tengo
pendiente?"), se marcan hechos ("ya está lo del lote 3") y se borran. Los vencidos van
primero y destacados. Las reglas están en docs/arquitectura.md, decisión "Pendientes".

El texto de un pendiente son las palabras de la persona: la IA lo recorta del mensaje. Para
encontrar el pendiente al que se refiere ("ya llamé al veterinario"), todas las palabras con
las que lo nombra tienen que estar en el pendiente, en su lote o en su campo, comparadas por
el principio ("llamé" y "llamar" coinciden). Si coincide con varios, no se toca ninguno y se
muestran las opciones, salvo que pida explícitamente todos.
"""

import re
from datetime import date
from typing import Annotated

from pydantic import BeforeValidator, Field

from app.ia.esquemas import Bandera, Esquema, EsquemaAccion, Fecha, SiNoVacio, texto
from app.infra.modelos import Establecimiento, Pendiente
from app.infra.texto import sin_tildes
from app.modulos.comun.registros import Lote
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto
from app.nucleo.cuaderno import Cuaderno
from app.nucleo.normalizar import clave_establecimiento
from app.salidas import whatsapp as formato
from app.salidas.whatsapp import SANGRIA
from app.salidas.whatsapp import SEPARADOR as LINEA

MAX_EN_LISTA = 20
MAX_OPCIONES = 8
MAX_REFERENCIAS = 10

SIN_PENDIENTES = "📭 No tenés nada pendiente."
NADA_CLARO = "🤔 No me quedó claro qué tenés pendiente.\nProbá con algo como: _tengo que revisar las aguadas el martes_"
CUAL = "🤔 ¿Cuál de tus pendientes? Decime cuál, por ejemplo: _ya está lo del lote 3_."

# Palabras que no sirven para distinguir un pendiente de otro.
_COMUNES = {
    "algo", "como", "cosa", "cosas", "desde", "esta", "este", "esto", "hacer", "hasta", "hice", "lista", "listo",
    "lote", "para", "pendiente", "pendientes", "tengo", "toda", "todas", "todo", "todos",
}  # fmt: skip
_PALABRA = re.compile(r"\w+")


# --- Esquemas ---------------------------------------------------------------------------

# Afuera de las clases: adentro, el campo `texto` taparía a la función `texto`.
Texto = Annotated[str | None, texto(200)]
Campo = Annotated[str | None, texto(120)]


class DatosPendiente(Esquema):
    texto: Texto = None  # qué hay que hacer, con las palabras de la persona
    lote: Lote = None
    vence: Fecha = None  # para cuándo


class AnotarPendiente(EsquemaAccion):
    pendiente: Annotated[DatosPendiente, SiNoVacio] = Field(default_factory=DatosPendiente)


class VerPendientes(EsquemaAccion):
    pass  # el campo, si pregunta por uno, viene en "establecimiento"


class ReferenciaPendiente(Esquema):
    """Con qué palabras nombra la persona un pendiente que ya anotó."""

    texto: Texto = None
    lote: Lote = None
    establecimiento: Campo = None
    todos: Bandera = False  # True SOLO si pide explícitamente todos los que coincidan

    def tiene_datos(self) -> bool:
        return bool(_raices(self.texto) or self.lote or self.establecimiento)


def _referencias(valor: object) -> object:
    return [r for r in valor[:MAX_REFERENCIAS] if isinstance(r, dict)] if isinstance(valor, list) else []


class SobrePendientes(EsquemaAccion):
    """Marcar hechos o borrar: a qué pendientes se refiere."""

    pendientes: Annotated[list[ReferenciaPendiente], BeforeValidator(_referencias)] = Field(default_factory=list)


# --- Cómo se ven ----------------------------------------------------------------------


def _vencido(p: Pendiente, hoy: date) -> bool:
    return p.vence is not None and p.vence < hoy


def _titulo(p: Pendiente) -> str:
    return p.texto[:1].upper() + p.texto[1:]


def _cuando(p: Pendiente, hoy: date) -> str | None:
    if p.vence is None:
        return None
    if p.vence < hoy:
        return f"*Venció el {formato.fecha_corta(p.vence)}*"
    if p.vence == hoy:
        return "📅 *Para hoy*"
    return f"📅 Para el {formato.fecha_corta(p.vence)}"


def tarjeta(p: Pendiente, hoy: date, lugar: bool = True, icono: str | None = None) -> str:
    """⚠️ *Llamar al veterinario*  /  Lote 3 · 📍 La Pastora · *Venció el Lun 12/10/2026*"""
    icono = icono or ("⚠️" if _vencido(p, hoy) else "📌")
    partes = [f"Lote {p.lote.nombre}"] if p.lote else []
    if lugar and p.establecimiento:
        partes.append(f"📍 {p.establecimiento.nombre}")
    if cuando := _cuando(p, hoy):
        partes.append(cuando)
    detalle = f"\n{SANGRIA}" + " · ".join(partes) if partes else ""
    return f"{icono} *{_titulo(p)}*{detalle}"


def linea(p: Pendiente) -> str:
    """Para listas de opciones: 📌 Revisar las aguadas · Lote 3 · 📍 El Retiro · 20/10"""
    partes = [f"📌 {_titulo(p)}"]
    if p.lote:
        partes.append(f"Lote {p.lote.nombre}")
    if p.establecimiento:
        partes.append(f"📍 {p.establecimiento.nombre}")
    if p.vence:
        partes.append(p.vence.strftime("%d/%m"))
    return " · ".join(partes)


def _ordenar(pendientes: list[Pendiente], hoy: date) -> list[Pendiente]:
    """Los vencidos primero (el más viejo arriba), después los que tienen fecha y al final
    los que no, en el orden en que se anotaron."""

    def clave(p: Pendiente) -> tuple[int, date, int]:
        grupo = 0 if _vencido(p, hoy) else 1 if p.vence else 2
        return grupo, p.vence or date.max, p.id

    return sorted(pendientes, key=clave)


def _cantidad(n: int) -> str:
    return f"{n} pendiente{'s' if n != 1 else ''}"


# --- Cómo se encuentra uno ------------------------------------------------------------


def _raices(texto: str | None) -> set[str]:
    """Las palabras que distinguen un pendiente, por su principio: "llamé" y "llamar" -> "llam".
    Los números van enteros ("405", "3")."""
    if not texto:
        return set()
    palabras = _PALABRA.findall(sin_tildes(texto.lower()))
    return {p if p.isdecimal() else p[:4] for p in palabras if p.isdecimal() or (len(p) >= 4 and p not in _COMUNES)}


def _coincide(p: Pendiente, ref: ReferenciaPendiente) -> bool:
    if ref.establecimiento and (
        p.establecimiento is None or p.establecimiento.clave != clave_establecimiento(ref.establecimiento)
    ):
        return False
    texto = sin_tildes(p.texto.lower())
    if ref.lote and not ((p.lote and p.lote.nombre == ref.lote) or f"lote {ref.lote}" in texto):
        return False
    donde = [p.texto, p.lote.nombre if p.lote else "", p.establecimiento.nombre if p.establecimiento else ""]
    return _raices(ref.texto) <= _raices(" ".join(donde))


def _describir(ref: ReferenciaPendiente) -> str:
    partes = [ref.texto[:60]] if ref.texto else []
    if ref.lote:
        partes.append(f"lote {ref.lote}")
    if ref.establecimiento:
        partes.append(f"en {ref.establecimiento[:60]}")
    return "_" + (" ".join(partes) or "eso") + "_"


def _elegir(ctx: Contexto, refs: list[ReferenciaPendiente], verbo: str) -> tuple[list[Pendiente], list[str]]:
    """Los pendientes a los que se refiere cada descripción, y los avisos de las que no
    señalan uno solo. `verbo`: lo que no se hizo si hay varios ("marqué", "borré")."""
    abiertos = ctx.cuaderno.pendientes()
    elegidos: dict[int, Pendiente] = {}
    avisos: list[str] = []
    for ref in refs:
        if not ref.tiene_datos() and not ref.todos:
            avisos.append("🤔 Uno de los pendientes que nombraste no lo pude identificar.")
            continue
        coinciden = [p for p in abiertos if _coincide(p, ref)]
        if not coinciden:
            avisos.append(f"🔍 No encontré un pendiente con {_describir(ref)}.")
        elif len(coinciden) > 1 and not ref.todos:
            opciones = "\n".join(f"{SANGRIA}› {linea(p)}" for p in coinciden[:MAX_OPCIONES])
            mas = f"\n{SANGRIA}_...y {len(coinciden) - MAX_OPCIONES} más_" if len(coinciden) > MAX_OPCIONES else ""
            avisos.append(
                f"🤔 *Hay {len(coinciden)} pendientes* que coinciden con {_describir(ref)}.\n"
                f"No {verbo} ninguno:\n\n{opciones}{mas}\n\nDecime cuál, o decí *todos*."
            )
        else:
            elegidos.update({p.id: p for p in coinciden})
    return list(elegidos.values()), avisos


def _sin_elegir(ctx: Contexto) -> str:
    """No dijo cuál: se muestran los que tiene para que elija."""
    abiertos = _ordenar(ctx.cuaderno.pendientes(), ctx.hoy)
    if not abiertos:
        return SIN_PENDIENTES
    opciones = "\n".join(f"{SANGRIA}› {linea(p)}" for p in abiertos[:MAX_OPCIONES])
    return f"{CUAL}\n\n{opciones}"


def _quedan(cuaderno: Cuaderno) -> str:
    n = len(cuaderno.pendientes())
    if not n:
        return "_No te queda nada pendiente._ 👌"
    return f"_Te queda{'n' if n != 1 else ''} {_cantidad(n)}._"


# --- Manejadores --------------------------------------------------------------------


def _campo(ctx: Contexto, nombrado: Establecimiento | None) -> Establecimiento | None:
    """El que nombra; si no, el de la sesión abierta o el campo actual. Nombrar un campo en
    un pendiente no cambia el campo actual."""
    if nombrado is not None:
        return nombrado
    sesion = ctx.cuaderno.sesion_abierta()
    return sesion.establecimiento if sesion is not None else ctx.usuario.establecimiento_actual


def anotar(ctx: Contexto, datos: AnotarPendiente) -> str:
    d = datos.pendiente
    if not d.texto:
        return NADA_CLARO
    cuaderno = ctx.cuaderno
    campo = _campo(ctx, cuaderno.establecimiento(datos.establecimiento))
    pendiente = Pendiente(establecimiento=campo, lote=cuaderno.lote(d.lote, campo), texto=d.texto, vence=d.vence)
    cuaderno.agregar_pendiente(pendiente)
    return (
        f"📌 *PENDIENTE ANOTADO*\n\n{tarjeta(pendiente, ctx.hoy, icono='📌')}\n\n{LINEA}\n"
        "_Cuando lo hagas, avisame. ¿Algo mal? Mandá *borrar*._"
    )


def ver(ctx: Contexto, datos: VerPendientes) -> str:
    clave = clave_establecimiento(datos.establecimiento)
    pendientes = _ordenar(ctx.cuaderno.pendientes(clave), ctx.hoy)
    if not pendientes:
        return SIN_PENDIENTES if not clave else f"📭 No tenés nada pendiente en {datos.establecimiento}."
    subtitulo = [f"📍 {pendientes[0].establecimiento.nombre}"] if clave and pendientes[0].establecimiento else []
    subtitulo.append(_cantidad(len(pendientes)))
    if vencidos := sum(_vencido(p, ctx.hoy) for p in pendientes):
        subtitulo.append(f"⚠️ {vencidos} vencido{'s' if vencidos != 1 else ''}")
    lista = "\n\n".join(tarjeta(p, ctx.hoy, lugar=not clave) for p in pendientes[:MAX_EN_LISTA])
    partes = [f"📌 *TUS PENDIENTES*\n{' · '.join(subtitulo)}", lista]
    if len(pendientes) > MAX_EN_LISTA:
        partes.append(f"_...y {len(pendientes) - MAX_EN_LISTA} más._")
    partes.append(f"{LINEA}\n_Cuando hagas uno, avisame: ya está lo del lote 3._")
    return "\n\n".join(partes)


def hecho(ctx: Contexto, datos: SobrePendientes) -> str:
    if not datos.pendientes:
        return _sin_elegir(ctx)
    elegidos, avisos = _elegir(ctx, datos.pendientes, "marqué")
    partes = []
    if elegidos:
        ctx.cuaderno.marcar_hechos([p.id for p in elegidos], ctx.ahora)
        hechos = "\n\n".join(tarjeta(p, ctx.hoy, icono="✅") for p in elegidos)
        partes.append(f"✅ *HECHO*\n\n{hechos}")
    partes += avisos
    if elegidos:
        partes.append(f"{LINEA}\n{_quedan(ctx.cuaderno)}")
    return "\n\n".join(partes)


def borrar(ctx: Contexto, datos: SobrePendientes) -> str:
    if not datos.pendientes:
        return _sin_elegir(ctx)
    elegidos, avisos = _elegir(ctx, datos.pendientes, "borré")
    partes = []
    if elegidos:
        borrados = "\n\n".join(tarjeta(p, ctx.hoy, icono="🗑️") for p in elegidos)
        ctx.cuaderno.borrar_pendientes([p.id for p in elegidos])
        partes.append(f"🗑️ *PENDIENTE BORRADO*\n\n{borrados}")
    return "\n\n".join(partes + avisos)


ACCIONES = [
    Accion("anotar_pendiente", AnotarPendiente, anotar),
    Accion("ver_pendientes", VerPendientes, ver),
    Accion("pendiente_hecho", SobrePendientes, hecho),
    Accion("borrar_pendiente", SobrePendientes, borrar),
]
