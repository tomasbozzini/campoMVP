"""Tacto (etapa 2, paso 3): vaca por vaca ("213 preñada cabeza CC 3, 214 vacía") o el cierre de
un lote ("88 preñadas: 60 cabeza, 20 cuerpo, 8 cola; 14 vacías, CC 3.2").

Cada vaca es un registro reproducción/tacto con su caravana; el cierre es otro, con el total de
vientres en `cantidad_animales`. Lo que dictó va tal cual en `extra["tacto"]` y las cuentas
(`calculos/tacto.py`) se hacen al mostrar: la IA no calcula nada. Cuándo es "tacto" y cuándo
"registrar", y las demás reglas: docs/arquitectura.md, etapa 2, paso 3.
"""

import uuid
from typing import Annotated, Any, Self

from pydantic import BeforeValidator, Field, model_validator

from app.calculos import tacto as cuentas
from app.ia.esquemas import Esquema, EsquemaAccion, Fecha, SiNoNada, SiNoVacio, texto
from app.infra.modelos import Evento
from app.infra.texto import sin_tildes
from app.modulos.comun.registros import Lote, fecha_valida
from app.nucleo import sesiones
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto
from app.salidas import whatsapp as formato
from app.salidas.whatsapp import SANGRIA
from app.salidas.whatsapp import SEPARADOR as LINEA

MAX_VACAS = 60  # por mensaje
MAX_CANTIDAD = 100_000
# Qué es cada registro de tacto, en extra["tacto"]["es"]. Los de "registrar" (tacto sin
# resultados) no tienen extra.
VACA, CIERRE = "vaca", "cierre"
CAMPOS_CIERRE = ("prenadas", "cabeza", "cuerpo", "cola", "vacias", "total", "cc")
# "Lote vaquillonas San Pedro": después de "lote" viene la categoría, no el nombre del lote.
CATEGORIAS_HACIENDA = {"vaca", "vaquillona", "ternera", "ternero", "novillo", "novillito", "toro", "vientre"}

NADA_CLARO = (
    "🤔 No me quedó claro el tacto.\n"
    "Dictá vaca por vaca (_213 preñada cabeza CC 3, 214 vacía_) o el cierre del lote "
    "(_88 preñadas, 14 vacías, CC 3.2_)."
)
_RESULTADOS = {"prenada": cuentas.PRENADA, "vacia": cuentas.VACIA}


def _palabra(opciones: dict[str, str] | tuple[str, ...]) -> BeforeValidator:
    """Una de esas palabras, escrita como sea: "Preñada", "vacías" -> "prenada", "vacia"."""

    def leer(valor: object) -> str | None:
        if not isinstance(valor, str):
            return None
        limpia = sin_tildes(valor).strip().lower().removesuffix("s")
        if isinstance(opciones, dict):
            return opciones.get(limpia)
        return limpia if limpia in opciones else None

    return BeforeValidator(leer)


def _cantidad(valor: object) -> int | None:
    if isinstance(valor, bool):
        return None
    try:
        numero = int(float(valor))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return numero if 0 <= numero <= MAX_CANTIDAD else None


def _cc(valor: object) -> float | None:
    """La condición corporal va de 1 a 5: lo demás no es una CC."""
    if isinstance(valor, bool):
        return None
    try:
        numero = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return numero if 1 <= numero <= 5 else None


def _vacas(valor: object) -> list[Any]:
    """Una lista de objetos, hasta MAX_VACAS; si no es una lista, ninguna."""
    return [v for v in valor if isinstance(v, dict)][:MAX_VACAS] if isinstance(valor, list) else []


Cantidad = Annotated[int | None, BeforeValidator(_cantidad)]
CC = Annotated[float | None, BeforeValidator(_cc)]


class VacaDictada(Esquema):
    caravana: Annotated[str | None, texto(40)] = None
    resultado: Annotated[str | None, _palabra(_RESULTADOS)] = None
    estadio: Annotated[str | None, _palabra(cuentas.ESTADIOS)] = None  # cabeza, cuerpo o cola
    cc: CC = None

    def vaca(self) -> cuentas.Vaca | None:
        """Cabeza, cuerpo o cola es preñada; sin preñada ni vacía, no se entendió."""
        if self.resultado == cuentas.VACIA:
            return cuentas.Vaca(cuentas.VACIA, None, self.cc)
        if self.resultado == cuentas.PRENADA or self.estadio:
            return cuentas.Vaca(cuentas.PRENADA, self.estadio, self.cc)
        return None


class CierreDictado(Esquema):
    prenadas: Cantidad = None
    cabeza: Cantidad = None
    cuerpo: Cantidad = None
    cola: Cantidad = None
    vacias: Cantidad = None
    total: Cantidad = None
    cc: CC = None

    def tiene_datos(self) -> bool:
        return any(getattr(self, campo) is not None for campo in CAMPOS_CIERRE)


class DatosTacto(Esquema):
    vacas: Annotated[list[VacaDictada], BeforeValidator(_vacas)] = Field(default_factory=list)
    cierre: Annotated[CierreDictado | None, SiNoNada] = None
    categoria_animal: Annotated[str | None, texto(40, minuscula=True)] = None
    lote: Lote = None
    fecha_evento: Fecha = None

    @model_validator(mode="after")
    def _lote_que_es_la_categoria(self) -> Self:
        """ "Lote vaquillonas": vaquillonas es la categoría y el lote queda vacío."""
        if self.lote and formato.singular(self.lote) in CATEGORIAS_HACIENDA:
            self.categoria_animal = self.categoria_animal or self.lote
            self.lote = None
        return self


class Tacto(EsquemaAccion):
    tacto: Annotated[DatosTacto, SiNoVacio] = Field(default_factory=DatosTacto)


# --- Los registros de tacto ---------------------------------------------------------


def _dictado(e: Evento) -> dict[str, Any] | None:
    datos = (e.extra or {}).get("tacto") if isinstance(e.extra, dict) else None
    return datos if isinstance(datos, dict) else None


def es_vaca(e: Evento) -> bool:
    return (_dictado(e) or {}).get("es") == VACA


def es_cierre(e: Evento) -> bool:
    return (_dictado(e) or {}).get("es") == CIERRE


def vaca_de(e: Evento) -> cuentas.Vaca:
    d = _dictado(e) or {}
    return cuentas.Vaca(d.get("resultado") or cuentas.VACIA, d.get("estadio"), d.get("cc"))


def cuentas_del_cierre(e: Evento) -> cuentas.Cuentas:
    d = _dictado(e) or {}
    return cuentas.de_cierre(**{campo: d.get(campo) for campo in CAMPOS_CIERRE})


def desde_el_ultimo_cierre(eventos: list[Evento]) -> list[Evento]:
    """Las vacas dictadas después del último cierre (los registros, del más viejo al más nuevo)."""
    vacas: list[Evento] = []
    for e in eventos:
        if es_cierre(e):
            vacas = []
        elif es_vaca(e):
            vacas.append(e)
    return vacas


# --- Cómo se ve ------------------------------------------------------------------------


def _decimal(valor: float) -> str:
    """86.3 -> "86,3"; 3.0 -> "3"."""
    return f"{valor:.1f}".replace(".", ",").removesuffix(",0")


def _cuantas(n: int) -> str:
    return f"{n} vaca{'s' if n != 1 else ''}"


def _resultado(v: cuentas.Vaca) -> str:
    if v.resultado == cuentas.VACIA:
        return "Vacía"
    return "Preñada" + (f" {v.estadio}" if v.estadio else "")


def _vaca(v: cuentas.Vaca) -> list[str]:
    """["Preñada cabeza", "CC 3"]"""
    return [_resultado(v), *([f"CC {_decimal(v.cc)}"] if v.cc is not None else [])]


def detalle(e: Evento) -> list[str]:
    """Lo que el tacto le suma al detalle de su registro (`formato.DETALLES`)."""
    if es_vaca(e):
        return _vaca(vaca_de(e))
    if not es_cierre(e):
        return []
    c = cuentas_del_cierre(e)
    partes = []
    if c.prenadas is not None:
        partes.append(f"{c.prenadas} preñadas" + (f" ({_decimal(c.porcentaje)} %)" if c.porcentaje is not None else ""))
    if c.vacias is not None:
        partes.append(f"{c.vacias} vacías")
    if c.cc is not None:
        partes.append(f"CC {_decimal(c.cc)}")
    return partes


def bloque(c: cuentas.Cuentas) -> str:
    """Las cuentas, una por línea: preñadas con el %, cabeza / cuerpo / cola, vacías, total y CC."""
    lineas = []
    if c.prenadas is not None:
        porcentaje = f" ({_decimal(c.porcentaje)} %)" if c.porcentaje is not None else ""
        lineas.append(f"Preñadas: *{c.prenadas}*{porcentaje}")
        if c.estadios:
            lineas.append("   › " + " · ".join(f"{n.capitalize()} {v}" for n, v in c.estadios.items()))
    if c.vacias is not None:
        lineas.append(f"Vacías: *{c.vacias}*")
    if c.total is not None:
        lineas.append(f"Total: *{c.total}* vientre{'s' if c.total != 1 else ''}")
    if c.cc is not None:
        de = f" (de {c.con_cc} con CC)" if c.con_cc and c.con_cc != c.total else ""
        lineas.append(f"CC promedio: *{_decimal(c.cc)}*{de}")
    return "\n".join(SANGRIA + linea for linea in lineas)


def _diferencia(d: cuentas.Diferencia) -> str:
    if d.que == "preñadas y vacías":
        return f"⚠️ Preñadas y vacías suman {d.suman}; dijiste {d.dijo} en total. Tomé {d.suman}."
    return f"⚠️ {d.que.capitalize()} suman {d.suman}; dijiste {d.dijo}."


def _comparacion(cierre: cuentas.Cuentas, vacas: list[Evento]) -> str | None:
    """Si las vacas dictadas en la sesión no dan lo mismo que el cierre: la diferencia, sin preguntar."""
    distintas = cuentas.comparar(cierre, cuentas.de_vacas([vaca_de(e) for e in vacas]))
    if not vacas or not distintas:
        return None
    filas = "\n".join(f"{SANGRIA}› {que.capitalize()}: {a} dictadas, {b} en el cierre" for que, a, b in distintas)
    return f"⚠️ Las vacas que dictaste en la sesión ({_cuantas(len(vacas))}) no dan lo mismo que el cierre:\n{filas}"


def bloque_sesion(eventos: list[Evento]) -> str | None:
    """Para el resumen de la sesión: las cuentas de las vacas que no tuvieron cierre."""
    vacas = desde_el_ultimo_cierre(eventos)
    if not vacas:
        return None
    sin_cierre = " sin cierre" if any(es_cierre(e) for e in eventos) else ""
    titulo = f"🩺 *Tacto vaca por vaca* · {_cuantas(len(vacas))}{sin_cierre}"
    return f"{titulo}\n{bloque(cuentas.de_vacas([vaca_de(e) for e in vacas]))}"


# --- El manejador -------------------------------------------------------------------------


def _sin_repetir(vacas: list[tuple[VacaDictada, cuentas.Vaca]]) -> list[tuple[VacaDictada, cuentas.Vaca]]:
    """Si una caravana viene dos veces en el mensaje ("la 213 vacía… no, la 213 preñada"), vale la última."""
    ultima = {v.caravana.lower(): i for i, (v, _) in enumerate(vacas) if v.caravana}
    return [(v, c) for i, (v, c) in enumerate(vacas) if not v.caravana or ultima[v.caravana.lower()] == i]


def manejar(ctx: Contexto, datos: Tacto) -> str:
    t, cuaderno = datos.tacto, ctx.cuaderno
    entendidas = [(v, c) for v in t.vacas if (c := v.vaca()) is not None]
    sin_entender = len(t.vacas) - len(entendidas)
    vacas = _sin_repetir(entendidas)
    cierre = t.cierre if t.cierre is not None and t.cierre.tiene_datos() else None
    if not vacas and cierre is None:
        return NADA_CLARO
    nombrado = cuaderno.establecimiento(datos.establecimiento) if datos.establecimiento else None
    if nombrado:
        ctx.usuario.establecimiento_actual = nombrado
    # Como "registrar": con una sesión abierta, lo que no nombra otro campo va a la sesión.
    destino = sesiones.destino(ctx, nombrado)
    campo, sesion = destino.establecimiento, destino.sesion
    lote = cuaderno.lote(t.lote, campo) or destino.lote_para("tacto")
    mensaje_id = str(uuid.uuid4())

    # La misma caravana dictada otra vez en la sesión reemplaza a la anterior: así se corrige.
    antes: dict[str, cuentas.Vaca] = {}
    if sesion is not None:
        previas = {e.caravana.lower(): e for e in cuaderno.registros_de_sesion(sesion) if es_vaca(e) and e.caravana}
        viejas = [previas[v.caravana.lower()] for v, _ in vacas if v.caravana and v.caravana.lower() in previas]
        antes = {e.caravana.lower(): vaca_de(e) for e in viejas if e.caravana}
        cuaderno.borrar([e.id for e in viejas])

    def registro(**datos_registro: Any) -> Evento:
        return Evento(
            establecimiento=campo,
            sesion_id=sesion.id if sesion else None,
            lote=lote,
            categoria="reproduccion",
            tipo="tacto",
            categoria_animal=t.categoria_animal,
            fecha_evento=fecha_valida(t.fecha_evento, ctx.hoy),
            mensaje_original=ctx.texto,
            mensaje_id=mensaje_id,
            **datos_registro,
        )

    nuevas = [
        registro(
            caravana=v.caravana,
            extra={"tacto": {"es": VACA, "resultado": c.resultado, "estadio": c.estadio, "cc": c.cc}},
        )
        for v, c in vacas
    ]
    del_cierre = cuentas.de_cierre(**cierre.model_dump(include=set(CAMPOS_CIERRE))) if cierre else None
    guardado_cierre = (
        registro(cantidad_animales=del_cierre.total, extra={"tacto": {"es": CIERRE, **cierre.model_dump()}})
        if cierre and del_cierre
        else None
    )
    cuaderno.agregar([*nuevas, *([guardado_cierre] if guardado_cierre else [])])

    cabecera = [f"📍 {campo.nombre}" if campo else "📍 _sin establecimiento_"]
    if t.categoria_animal:
        cabecera.append(t.categoria_animal.capitalize())
    if lote:
        cabecera.append(f"Lote {lote.nombre}")
    if sesion:
        cabecera.append("▶️ en la sesión")
    if nuevas and (fecha := nuevas[0].fecha_evento) != ctx.hoy:
        cabecera.append(f"📅 {formato.fecha_corta(fecha)}")
    elif guardado_cierre and guardado_cierre.fecha_evento != ctx.hoy:
        cabecera.append(f"📅 {formato.fecha_corta(guardado_cierre.fecha_evento)}")
    donde = " · ".join(cabecera)

    partes: list[str] = []
    eventos_sesion = cuaderno.registros_de_sesion(sesion) if sesion else []
    if nuevas:
        lineas = []
        for v, c in vacas:
            nombre = f"{v.caravana} · " if v.caravana else ""
            vieja = antes.get(v.caravana.lower()) if v.caravana else None
            cambio = f" _(antes: {_resultado(vieja).lower()})_" if vieja else ""
            lineas.append(f"{SANGRIA}› {nombre}{' · '.join(_vaca(c))}{cambio}")
        partes.append(f"🩺 *TACTO ANOTADO* · {_cuantas(len(nuevas))}\n{donde}\n\n" + "\n".join(lineas))
        if sesion is not None and guardado_cierre is None:
            llevadas = desde_el_ultimo_cierre(eventos_sesion)
            desde = "Desde el último cierre" if any(es_cierre(e) for e in eventos_sesion) else "En la sesión"
            partes.append(
                f"📊 *{desde}* · {_cuantas(len(llevadas))}\n{bloque(cuentas.de_vacas([vaca_de(e) for e in llevadas]))}"
            )
        elif sesion is None and guardado_cierre is None:
            if len(nuevas) > 1:
                partes.append(f"📊 *En este mensaje*\n{bloque(cuentas.de_vacas([c for _, c in vacas]))}")
            partes.append("_Con una sesión abierta (arranco tacto en …) te voy sumando las vacas._")
    if guardado_cierre and del_cierre:
        encabezado = f"🩺 *CIERRE DE TACTO*\n{donde}" if not nuevas else "🩺 *CIERRE DE TACTO*"
        partes.append(f"{encabezado}\n\n{bloque(del_cierre)}")
        partes += [_diferencia(d) for d in del_cierre.diferencias]
        anteriores = [e for e in eventos_sesion if e.id < guardado_cierre.id]
        if comparacion := _comparacion(del_cierre, desde_el_ultimo_cierre(anteriores)):
            partes.append(comparacion)
    if sin_entender:
        cuales = "Una vaca no la entendí" if sin_entender == 1 else f"{sin_entender} vacas no las entendí"
        partes.append(f"🤔 {cuales}: decime si está preñada (cabeza, cuerpo o cola) o vacía.")
    if destino.aviso:
        partes.append(destino.aviso)
    pie = "Volvé a dictar la vaca o mandá *borrar*." if not guardado_cierre else "Mandá *borrar* y dictalo de nuevo."
    partes.append(f"{LINEA}\n_¿Algo mal? {pie}_")
    return "\n\n".join(partes)


ACCION = Accion("tacto", Tacto, manejar)
