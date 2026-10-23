"""Raspaje de toros (etapa 2, paso 4): el resultado de cada toro ("Toro caravana 405 raspaje
negativo, el 412 presentó muestra dudosa, repetir en 15 días") o el que llega del laboratorio.

Cada toro es un animal de la tabla `animales` (por RP o caravana, en su campo) y cada raspaje un
registro sanidad/raspaje de ese animal, con lo que dijo en `extra["raspaje"]`: el resultado
(negativo, positivo, dudoso o, si no lo dice, esperando; nunca "apto"), el número de muestreo y
la fecha para repetir, que calcula el código (`calculos/raspaje.py`). El resultado de laboratorio
es otro registro, que le pone el resultado al último raspaje del toro y lo devuelve al borrarse.
Las reglas: docs/arquitectura.md, etapa 2, paso 4.
"""

import re
import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated, Any

from pydantic import BeforeValidator, Field

from app.calculos import raspaje as cuentas
from app.ia.esquemas import Bandera, Esquema, EsquemaAccion, Fecha, SiNoVacio, limpiar_texto, texto
from app.infra.config import config
from app.infra.marca import NOMBRE
from app.infra.modelos import Animal, Establecimiento, Evento, Pendiente
from app.infra.modelos import Lote as LoteDelCampo
from app.infra.texto import sin_tildes
from app.modulos.comun import registrar
from app.modulos.comun.consultar import FiltrosConsulta
from app.modulos.comun.exportar import descripcion, membrete
from app.modulos.comun.registros import DatosEvento, Lote, fecha_valida
from app.nucleo import sesiones
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto
from app.salidas import pdf
from app.salidas import whatsapp as formato
from app.salidas.whatsapp import SANGRIA
from app.salidas.whatsapp import SEPARADOR as LINEA

MAX_TOROS = 60  # por mensaje
MAX_MUESTREO = 20
TIPO, CATEGORIA, TORO = "raspaje", "sanidad", "toro"
# Qué es cada registro de raspaje, en extra["raspaje"]["es"]. Los de "registrar" (raspó sin
# decir qué toros) no tienen extra.
RASPAJE, LABORATORIO = "raspaje", "laboratorio"
NEGATIVO, POSITIVO, DUDOSO = "negativo", "positivo", "dudoso"
GENERAL = ""  # el resultado sin decir la enfermedad (o de las dos)
ESPERANDO = "Esperando resultado"
PIE_RASPAJES = f"{pdf.PIE} Es un registro de trabajo: no es un certificado."

NADA_CLARO = (
    "🤔 No me quedó claro el raspaje.\n"
    "Dictá cada toro con su caravana o RP y el resultado: _toro 405 negativo, el 412 dudoso_."
)
_RESULTADOS = {
    "negativo": NEGATIVO, "negativa": NEGATIVO, "positivo": POSITIVO, "positiva": POSITIVO,
    "dudoso": DUDOSO, "dudosa": DUDOSO, "sospechoso": DUDOSO, "sospechosa": DUDOSO,
}  # fmt: skip
_ENFERMEDADES = {
    "tricomoniasis": "tricomoniasis", "trico": "tricomoniasis", "tricomonas": "tricomoniasis",
    "campylobacter": "campylobacter", "campylo": "campylobacter", "campilobacter": "campylobacter",
    "campylobacteriosis": "campylobacter", "campilobacteriosis": "campylobacter",
}  # fmt: skip
_NOMBRES_ENFERMEDAD = {"tricomoniasis": "Tricomoniasis", "campylobacter": "Campylobacter"}
_PREFIJO = re.compile(r"^(?:toro|rp|caravana|car\.?|n[°º.]?|nro\.?|numero|#)\s*", re.IGNORECASE)


# --- Esquemas ----------------------------------------------------------------------------


def _de(opciones: dict[str, str]) -> BeforeValidator:
    """Una de esas palabras, escrita como sea: "Negativa" -> "negativo", "Trico" -> "tricomoniasis"."""

    def leer(valor: object) -> str | None:
        return opciones.get(sin_tildes(valor).strip().lower()) if isinstance(valor, str) else None

    return BeforeValidator(leer)


def _identificacion(valor: object) -> str | None:
    """ "RP 412", "toro caravana 405" -> "412", "405"."""
    limpio = limpiar_texto(valor, 60)
    if limpio is None:
        return None
    while (sin := _PREFIJO.sub("", limpio, count=1)) != limpio:
        limpio = sin
    return limpio[:40] or None


def _muestreo(valor: object) -> int | None:
    if isinstance(valor, bool) or not isinstance(valor, int | float | str):
        return None
    try:
        numero = int(float(valor))
    except ValueError:
        return None
    return numero if 1 <= numero <= MAX_MUESTREO else None


def _toros(valor: object) -> list[Any]:
    return [t for t in valor if isinstance(t, dict)][:MAX_TOROS] if isinstance(valor, list) else []


Identificacion = Annotated[str | None, BeforeValidator(_identificacion)]


class ToroDictado(Esquema):
    caravana: Identificacion = None
    rp: Identificacion = None
    resultado: Annotated[str | None, _de(_RESULTADOS)] = None  # None: esperando el resultado
    enfermedad: Annotated[str | None, _de(_ENFERMEDADES)] = None  # None: las dos o no lo dice
    muestreo: Annotated[int | None, BeforeValidator(_muestreo)] = None  # solo si dice el número
    repetir_en: Annotated[str | None, texto(40)] = None  # como lo dijo: "15 días"

    def clave(self) -> str | None:
        return (self.rp or self.caravana or "").lower() or None


class DatosRaspaje(Esquema):
    toros: Annotated[list[ToroDictado], BeforeValidator(_toros)] = Field(default_factory=list)
    laboratorio: Bandera = False  # el resultado de muestras ya tomadas
    lote: Lote = None
    fecha_evento: Fecha = None


class Raspaje(EsquemaAccion):
    raspaje: Annotated[DatosRaspaje, SiNoVacio] = Field(default_factory=DatosRaspaje)


class Toro:
    """Lo que dictó de un toro en el mensaje, juntando sus líneas (una por enfermedad)."""

    def __init__(self, dictado: ToroDictado) -> None:
        self.rp, self.caravana = dictado.rp, dictado.caravana
        self.resultados: dict[str, str] = {}
        self.muestreo: int | None = None
        self.repetir_en: str | None = None
        self.sumar(dictado)

    def sumar(self, dictado: ToroDictado) -> None:
        self.rp, self.caravana = self.rp or dictado.rp, self.caravana or dictado.caravana
        if dictado.resultado:
            self.resultados[dictado.enfermedad or GENERAL] = dictado.resultado
        self.muestreo = dictado.muestreo or self.muestreo
        self.repetir_en = dictado.repetir_en or self.repetir_en

    @property
    def nombre(self) -> str:
        return f"RP {self.rp}" if self.rp else self.caravana or "?"


def _juntar(dictados: list[ToroDictado]) -> tuple[list[Toro], int]:
    """Los toros del mensaje, en orden y sin repetir, y cuántos vinieron sin RP ni caravana."""
    toros: dict[str, Toro] = {}
    sin_nombre = 0
    for d in dictados:
        if (clave := d.clave()) is None:
            sin_nombre += 1
        elif clave in toros:
            toros[clave].sumar(d)
        else:
            toros[clave] = Toro(d)
    return list(toros.values()), sin_nombre


# --- Los registros de raspaje ----------------------------------------------------------


def _dictado(e: Evento) -> dict[str, Any]:
    datos = (e.extra or {}).get("raspaje") if isinstance(e.extra, dict) else None
    return datos if isinstance(datos, dict) else {}


def es_raspaje(e: Evento) -> bool:
    return e.tipo == TIPO and _dictado(e).get("es") == RASPAJE


def es_laboratorio(e: Evento) -> bool:
    return e.tipo == TIPO and _dictado(e).get("es") == LABORATORIO


def muestreo_de(e: Evento) -> int:
    numero = _dictado(e).get("muestreo")
    return numero if isinstance(numero, int) else 1


def _resultados(datos: dict[str, Any]) -> dict[str, str]:
    crudos = datos.get("resultados")
    return {k: v for k, v in crudos.items() if isinstance(k, str) and isinstance(v, str)} if crudos else {}


def resultados_de(e: Evento) -> dict[str, str]:
    """El resultado de un raspaje: el que dijo y, encima, el del laboratorio si llegó (el del
    laboratorio sin enfermedad reemplaza todo)."""
    d = _dictado(e)
    propios = _resultados(d)
    lab = _resultados(d.get("laboratorio") or {})
    if GENERAL in lab:
        return lab
    return {**propios, **lab}


def texto_resultado(resultados: dict[str, str]) -> str:
    """ "Negativo", "Tricomoniasis: negativo · Campylobacter: positivo", "Esperando resultado"."""
    if not resultados:
        return ESPERANDO
    partes = [resultados[GENERAL].capitalize()] if GENERAL in resultados else []
    partes += [f"{_NOMBRES_ENFERMEDAD[k]}: {v}" for k, v in sorted(resultados.items()) if k in _NOMBRES_ENFERMEDAD]
    return " · ".join(partes)


def _ordinal(n: int) -> str:
    return f"{n}.°"


def _repetir(e: Evento) -> date | None:
    fecha = _dictado(e).get("repetir")
    try:
        return date.fromisoformat(fecha) if isinstance(fecha, str) else None
    except ValueError:
        return None


def _toro_de(e: Evento) -> str:
    return e.animal.nombre if e.animal else e.caravana or "?"


def detalle(e: Evento) -> list[str]:
    """Lo que el raspaje le suma al detalle de su registro (`formato.DETALLES`): el RP (la
    caravana ya la muestra el registro), el muestreo, el resultado y la repetición."""
    rp = [f"RP {e.animal.rp}"] if e.animal and e.animal.rp and not e.caravana else []
    if es_raspaje(e):
        lab = " (laboratorio)" if _dictado(e).get("laboratorio") else ""
        repetir = [f"Repetir el {fecha:%d/%m}"] if (fecha := _repetir(e)) else []
        return [*rp, f"{_ordinal(muestreo_de(e))} raspaje", texto_resultado(resultados_de(e)) + lab, *repetir]
    if es_laboratorio(e):
        return [*rp, "Resultado de laboratorio", texto_resultado(_resultados(_dictado(e)))]
    return []


def por_resultado(eventos: list[Evento]) -> dict[str, int]:
    """Cuántos raspajes hay de cada resultado: {"Negativo": 10, "Dudoso": 1}."""
    cuantos: dict[str, int] = defaultdict(int)
    for e in eventos:
        cuantos[texto_resultado(resultados_de(e))] += 1
    return dict(cuantos)


def _cuantos_toros(n: int) -> str:
    return f"{n} toro{'s' if n != 1 else ''}"


def bloque_sesion(eventos: list[Evento]) -> str | None:
    """Para el resumen de la sesión: los toros raspados, por resultado."""
    raspajes = [e for e in eventos if es_raspaje(e)]
    if not raspajes:
        return None
    filas = " · ".join(f"{que} {n}" for que, n in por_resultado(raspajes).items())
    return f"🔬 *Raspaje* · {_cuantos_toros(len(raspajes))}\n{SANGRIA}{filas}"


# --- El PDF "Registro de raspajes" ---------------------------------------------------------


def armar_pdf(ctx: Contexto, f: FiltrosConsulta, eventos: list[Evento]) -> bytes | None:
    """Una fila por raspaje, con el resultado del laboratorio si llegó; None si no hay
    raspajes de toros identificados (va el PDF de siempre)."""
    raspajes = sorted((e for e in eventos if es_raspaje(e)), key=lambda e: (e.fecha_evento, e.id))
    if not raspajes:
        return None
    filas = [
        [
            e.fecha_evento.strftime("%d/%m/%Y"),
            e.nombre_establecimiento or "-",
            _toro_de(e),
            _ordinal(muestreo_de(e)),
            texto_resultado(resultados_de(e)),
            r.strftime("%d/%m/%Y") if (r := _repetir(e)) else "-",
        ]
        for e in raspajes
    ]
    tabla = pdf.Tabla(("Fecha", "Campo", "Toro", "Muestreo", "Resultado", "Repetir"), (16, 24, 22, 14, 44, 16), filas)
    resumen = [f"Toros raspados: {len(raspajes)}", *(f"{que}: {n}" for que, n in por_resultado(raspajes).items())]
    return pdf.documento(
        membrete(ctx.usuario),
        "Registro de raspajes",
        descripcion(f, raspajes),
        resumen,
        tabla,
        ctx.ahora.astimezone(config.zona_horaria),
        pie=PIE_RASPAJES,
        titulo_resumen="Resultados",
    )


NOMBRE_PDF = f"{NOMBRE}-raspajes"


# --- El manejador -----------------------------------------------------------------------


def _pendientes(
    ctx: Contexto, campo: Establecimiento | None, lote: LoteDelCampo | None, repeticiones: dict[date, list[str]]
) -> dict[date, Pendiente]:
    """Un pendiente por fecha para repetir: "Repetir raspaje: toros 412 y 415"."""
    anotados = {}
    for vence, nombres in sorted(repeticiones.items()):
        lista = nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + f" y {nombres[-1]}"
        texto_pendiente = f"Repetir raspaje: {'toro' if len(nombres) == 1 else 'toros'} {lista}"
        if len(texto_pendiente) > 120:
            texto_pendiente = f"Repetir raspaje de {len(nombres)} toros"
        p = Pendiente(establecimiento=campo, lote=lote, texto=texto_pendiente, vence=vence)
        ctx.cuaderno.agregar_pendiente(p)
        anotados[vence] = p
    return anotados


def _avisos_repetir(toro: Toro, desde: date) -> tuple[date | None, str | None]:
    fecha = cuentas.fecha_para_repetir(desde, toro.repetir_en)
    if toro.repetir_en and fecha is None:
        return (
            None,
            f"🤔 No entendí cuándo repetir el raspaje del toro {toro.nombre} (_{toro.repetir_en}_): decime en cuántos días.",
        )
    return fecha, None


def _cabecera(campo: Establecimiento | None, lote: LoteDelCampo | None, en_sesion: bool, fecha: date, hoy: date) -> str:
    partes = [f"📍 {campo.nombre}" if campo else "📍 _sin establecimiento_"]
    if lote:
        partes.append(f"Lote {lote.nombre}")
    if en_sesion:
        partes.append("▶️ en la sesión")
    if fecha != hoy:
        partes.append(f"📅 {formato.fecha_corta(fecha)}")
    return " · ".join(partes)


def _lineas_pendientes(anotados: dict[date, Pendiente]) -> list[str]:
    return [
        f"📌 *PENDIENTE ANOTADO*\n{SANGRIA}{p.texto} · 📅 Para el {formato.fecha_corta(vence)}"
        for vence, p in anotados.items()
    ]


def _raspar(ctx: Contexto, t: DatosRaspaje, toros: list[Toro], nombrado: Establecimiento | None) -> list[str]:
    """Los raspajes de los toros: uno por toro, con su muestreo y su repetición."""
    cuaderno = ctx.cuaderno
    if nombrado:
        ctx.usuario.establecimiento_actual = nombrado
    destino = sesiones.destino(ctx, nombrado)
    campo, sesion = destino.establecimiento, destino.sesion
    lote = cuaderno.lote(t.lote, campo) or destino.lote_para(TIPO)
    fecha = fecha_valida(t.fecha_evento, ctx.hoy)
    mensaje_id = str(uuid.uuid4())

    avisos: list[str] = []
    filas: list[tuple[Toro, Animal, int, date | None, dict[str, str] | None]] = []
    for toro in toros:
        animal = cuaderno.animal(toro.rp, toro.caravana, campo, TORO)
        if animal is None:
            continue
        anteriores = [e for e in cuaderno.registros_del_animal(animal, TIPO) if es_raspaje(e)]
        # El mismo toro dictado otra vez el mismo día reemplaza al anterior: así se corrige.
        mismo_dia = [e for e in anteriores if e.fecha_evento == fecha]
        antes = resultados_de(mismo_dia[-1]) if mismo_dia else None
        cuaderno.borrar([e.id for e in mismo_dia])
        quedan = [(e.fecha_evento, muestreo_de(e)) for e in anteriores if e not in mismo_dia]
        calculado = cuentas.muestreo(quedan, fecha)
        if toro.muestreo and toro.muestreo != calculado:
            avisos.append(
                f"⚠️ Toro {toro.nombre}: dijiste {_ordinal(toro.muestreo)} raspaje; en lo anotado "
                f"sería el {_ordinal(calculado)}. Quedó el {_ordinal(toro.muestreo)}."
            )
        repetir, aviso = _avisos_repetir(toro, fecha)
        if aviso:
            avisos.append(aviso)
        filas.append((toro, animal, toro.muestreo or calculado, repetir, antes))

    repeticiones: dict[date, list[str]] = defaultdict(list)
    for toro, _, _, repetir, _ in filas:
        if repetir:
            repeticiones[repetir].append(toro.nombre)
    # Los pendientes antes que los registros: "borrar" deshace los registros (y con ellos, los pendientes).
    anotados = _pendientes(ctx, campo, lote, repeticiones)
    nuevos = [
        Evento(
            establecimiento=campo,
            sesion_id=sesion.id if sesion else None,
            lote=lote,
            categoria=CATEGORIA,
            tipo=TIPO,
            categoria_animal=TORO,
            caravana=toro.caravana if not toro.rp else None,
            animal_id=animal.id,
            fecha_evento=fecha,
            mensaje_original=ctx.texto,
            mensaje_id=mensaje_id,
            extra={
                "raspaje": {
                    "es": RASPAJE,
                    "resultados": toro.resultados,
                    "muestreo": muestreo,
                    "repetir": repetir.isoformat() if repetir else None,
                },
                **({"pendientes": [anotados[repetir].id]} if repetir else {}),
            },
        )
        for toro, animal, muestreo, repetir, _ in filas
    ]
    cuaderno.agregar(nuevos)

    lineas = []
    for (toro, _, muestreo, repetir, antes), e in zip(filas, nuevos, strict=True):
        cambio = f" _(antes: {texto_resultado(antes).lower()})_" if antes is not None else ""
        cuando = f" · repetir el {repetir:%d/%m}" if repetir else ""
        lineas.append(
            f"{SANGRIA}› Toro {toro.nombre} · {_ordinal(muestreo)} raspaje · {texto_resultado(resultados_de(e))}{cambio}{cuando}"
        )
    partes = [
        f"🔬 *RASPAJE ANOTADO* · {_cuantos_toros(len(nuevos))}\n"
        f"{_cabecera(campo, lote, sesion is not None, fecha, ctx.hoy)}\n\n" + "\n".join(lineas),
        *_lineas_pendientes(anotados),
        *avisos,
    ]
    if destino.aviso:
        partes.append(destino.aviso)
    return partes


def _laboratorio(ctx: Contexto, toros: list[Toro], nombrado: Establecimiento | None) -> list[str]:
    """El resultado que llegó del laboratorio: se le pone al último raspaje de cada toro."""
    cuaderno = ctx.cuaderno
    destino = sesiones.destino(ctx, nombrado)
    mensaje_id = str(uuid.uuid4())
    avisos: list[str] = []
    encontrados: list[tuple[Toro, Evento]] = []
    for toro in toros:
        if nombrado is not None:
            candidatos = [a] if (a := cuaderno.animal_existente(toro.rp, toro.caravana, nombrado)) else []
        else:
            candidatos = cuaderno.animales_en_todos_los_campos(toro.rp, toro.caravana)
            del_destino = [
                a for a in candidatos if destino.establecimiento and a.establecimiento_id == destino.establecimiento.id
            ]
            candidatos = del_destino or candidatos
        raspados = [
            (a, ultimo)
            for a in candidatos
            if (ultimo := next((e for e in reversed(cuaderno.registros_del_animal(a, TIPO)) if es_raspaje(e)), None))
        ]
        if not raspados:
            avisos.append(
                f"🔍 No encontré un raspaje anotado del toro {toro.nombre}. Dictame el raspaje "
                f"(_toro {toro.nombre} raspaje negativo, el martes_)."
            )
        elif len(raspados) > 1:
            campos = " y ".join(a.establecimiento.nombre if a.establecimiento else "sin campo" for a, _ in raspados)
            avisos.append(f"🤔 Hay un toro {toro.nombre} en {campos}: decime de qué campo es el resultado.")
        elif not toro.resultados:
            avisos.append(
                f"🤔 No entendí el resultado del toro {toro.nombre}: decime si dio negativo, positivo o dudoso."
            )
        else:
            encontrados.append((toro, raspados[0][1]))
    if not encontrados:
        return avisos

    repeticiones: dict[date, list[str]] = defaultdict(list)
    fechas: list[date | None] = []
    for toro, _ in encontrados:
        repetir, aviso = _avisos_repetir(toro, ctx.hoy)
        fechas.append(repetir)
        if aviso:
            avisos.append(aviso)
        if repetir:
            repeticiones[repetir].append(toro.nombre)
    primero = encontrados[0][1]
    anotados = _pendientes(ctx, primero.establecimiento, primero.lote, repeticiones)

    lineas = []
    for (toro, raspado), repetir in zip(encontrados, fechas, strict=True):
        antes_extra = dict(raspado.extra or {})
        antes = resultados_de(raspado)
        datos = _dictado(raspado)
        lab = Evento(
            establecimiento=raspado.establecimiento,
            lote=raspado.lote,
            categoria=CATEGORIA,
            tipo=TIPO,
            categoria_animal=TORO,
            caravana=raspado.caravana,
            animal_id=raspado.animal_id,
            fecha_evento=ctx.hoy,
            mensaje_original=ctx.texto,
            mensaje_id=mensaje_id,
            extra={
                "raspaje": {"es": LABORATORIO, "de": raspado.id, "resultados": toro.resultados},
                **({"pendientes": [anotados[repetir].id]} if repetir else {}),
            },
        )
        cuaderno.agregar([lab])
        anterior_lab = _resultados(datos.get("laboratorio") or {})
        del_lab = toro.resultados if GENERAL in toro.resultados else {**anterior_lab, **toro.resultados}
        despues = {
            **antes_extra,
            "raspaje": {
                **datos,
                "laboratorio": {"resultados": del_lab, "fecha": ctx.hoy.isoformat(), "evento": lab.id},
            },
        }
        raspado.extra = despues
        lab.extra = {**(lab.extra or {}), "deshacer": {"evento": raspado.id, "antes": antes_extra, "despues": despues}}
        cuaderno.db.flush()
        cuando = f" · repetir el {repetir:%d/%m}" if repetir else ""
        lineas.append(
            f"{SANGRIA}› Toro {toro.nombre} · {_ordinal(muestreo_de(raspado))} raspaje del "
            f"{raspado.fecha_evento:%d/%m} · {texto_resultado(resultados_de(raspado))} "
            f"_(antes: {texto_resultado(antes).lower()})_{cuando}"
        )
    return [
        f"🧪 *RESULTADO DE LABORATORIO* · {_cuantos_toros(len(encontrados))}\n\n" + "\n".join(lineas),
        *_lineas_pendientes(anotados),
        *avisos,
    ]


def _como_registro(ctx: Contexto, datos: Raspaje) -> str:
    """ "Raspamos 12 toros en La Pastora", sin nombrar ningún toro, es "registrar" (plan, paso 4);
    si la IA lo manda como "raspaje", se anota igual, con el mismo manejador."""
    evento = DatosEvento.model_construct(
        categoria=CATEGORIA,
        tipo=TIPO,
        categoria_animal="toros",
        lote=datos.raspaje.lote,
        fecha_evento=datos.raspaje.fecha_evento,
    )
    pedido = registrar.Registrar.model_construct(
        intencion="registrar", establecimiento=datos.establecimiento, eventos=[evento]
    )
    return registrar.manejar(ctx, pedido)


def manejar(ctx: Contexto, datos: Raspaje) -> str:
    t = datos.raspaje
    if not t.toros:
        return _como_registro(ctx, datos)
    toros, sin_nombre = _juntar(t.toros)
    if not toros:
        return NADA_CLARO
    nombrado = ctx.cuaderno.establecimiento(datos.establecimiento) if datos.establecimiento else None
    partes = _laboratorio(ctx, toros, nombrado) if t.laboratorio else _raspar(ctx, t, toros, nombrado)
    if sin_nombre:
        cuales = "Un toro no lo entendí" if sin_nombre == 1 else f"{sin_nombre} toros no los entendí"
        partes.append(f"🤔 {cuales}: decime su caravana o su RP.")
    pie = "Volvé a dictar el toro o mandá *borrar*." if not t.laboratorio else "Mandá *borrar* y dictalo de nuevo."
    partes.append(f"{LINEA}\n_¿Algo mal? {pie}_")
    return "\n\n".join(partes)


ACCION = Accion("raspaje", Raspaje, manejar)
