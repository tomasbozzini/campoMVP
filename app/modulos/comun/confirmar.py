"""Preguntas que esperan una respuesta: borrados grandes, correcciones de muchos pendientes,
campos parecidos a otro y fechas dudosas.

- Todo borrado de registros o pendientes que llega por la IA pide confirmación, sea de 1 o de
  10 (paso 8.7.2): un error de la IA nunca borra nada solo. El atajo exacto `borrar` no
  pregunta. Corregir 4 o más pendientes de una vez, también.
- Antes de crear un campo con un nombre muy parecido a uno que ya existe ("Omu" y "El
  Ombú"), se pregunta si es el mismo. Lo del mensaje se hace después de la respuesta: *sí*
  lo anota en el que ya existe, *no* crea el nuevo, *cambiale el nombre* le pone al que ya
  existe el nombre nuevo y lo anota ahí, y "cancelá" o "dejá" no anota nada.
- Unir dos campos o dos lotes ("Omu y El Ombú son el mismo campo") pide confirmación y
  muestra qué pasa al que queda. Borrar un campo o un lote, también, mostrando lo que se borra.
- Al renombrar, unir o borrar un campo o un lote que no existe, si hay uno parecido ("Lomu" y
  Omu), se pregunta si es ese: *sí* sigue con ese, *no* cancela (paso 8.7.4). Lo del mensaje
  se hace después, como con un campo parecido.
- Si el día de la semana y el número no coinciden ("el viernes 22" cuando el 22 es jueves),
  se pregunta para cuándo, con las dos fechas: *1* o *2*, o el día ("el jueves", "el 23").
  Lo del mensaje se hace después, como con un campo parecido.

La pregunta queda esperando durante 10 minutos. *no* la cancela y se aceptan las variantes de
siempre ("dale", "sí, borrá", "no, dejá"): ver `nucleo/respuestas.py`. Cualquier otro mensaje
la descarta y va a la IA con la pregunta como contexto, por si la cancela con otras palabras.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.infra.modelos import BorradoPendiente, Establecimiento, Lote
from app.nucleo import preguntas, respuestas
from app.nucleo.contexto import Contexto
from app.nucleo.cuaderno import Contenido, Cuaderno, NombreParecido
from app.nucleo.normalizar import clave_establecimiento, normalizar_lote
from app.salidas import whatsapp as formato
from app.salidas.whatsapp import SANGRIA
from app.salidas.whatsapp import SEPARADOR as LINEA

CONFIRMAR_DESDE = 4
CONFIRMAR_MINUTOS = 10
MAX_EN_LISTA = 10

# Qué espera confirmación.
REGISTROS, PENDIENTES, CORREGIR, CAMPO, FECHA = "registros", "pendientes", "corregir", "campo", "fecha"
UNIR_CAMPOS, UNIR_LOTES = "unir_campo", "unir_lote"  # `que` tiene hasta 10 letras
BORRAR_CAMPO, BORRAR_LOTE = "baja_campo", "baja_lote"
PARECIDO = "parecido"

PASO_EL_TIEMPO = "⏱️ Pasó mucho tiempo desde que lo pediste y no {hice}.\nSi querés, pedilo de nuevo."


def _lista(titulo: str, lineas: list[str]) -> list[str]:
    texto = [f"{titulo}\n"]
    texto += [f"{SANGRIA}› {linea}" for linea in lineas[:MAX_EN_LISTA]]
    if len(lineas) > MAX_EN_LISTA:
        texto.append(f"{SANGRIA}_...y {len(lineas) - MAX_EN_LISTA} más_")
    return texto


def _cuantos(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


def _a_borrar(pendiente: BorradoPendiente) -> tuple[list[int], list[int]]:
    """Los registros y los pendientes de un borrado esperando el *sí*. Si son registros, los
    pendientes del mismo mensaje van en `datos`."""
    if pendiente.que == PENDIENTES:
        return [], list(pendiente.ids)
    return list(pendiente.ids), [int(i) for i in (pendiente.datos or {}).get("pendientes", [])]


def pedir(cuaderno: Cuaderno, que: str, ids: list[int], lineas: list[str], ahora: datetime) -> str:
    """Deja el borrado de esos registros (`REGISTROS`) o pendientes (`PENDIENTES`) esperando el
    *sí* y muestra qué se va a borrar (`lineas`, una por cosa). Todo borrado que llega por la IA
    pasa por acá, sea de 1 o de 10 (paso 8.7.2). Si el mismo mensaje ya dejó otro borrado
    esperando ("borrá la lluvia y el pendiente de Juan"), lo suma: una sola confirmación."""
    registros, pendientes = (list(ids), []) if que == REGISTROS else ([], list(ids))
    previo = cuaderno.borrado_esperando()
    if previo is not None and previo.que in (REGISTROS, PENDIENTES):
        antes_registros, antes_pendientes = _a_borrar(previo)
        registros, pendientes = antes_registros + registros, antes_pendientes + pendientes
    if registros:
        cuaderno.guardar_borrado_pendiente(
            registros, ahora, REGISTROS, {"pendientes": pendientes} if pendientes else None
        )
    else:
        cuaderno.guardar_borrado_pendiente(pendientes, ahora, PENDIENTES)
    cosa = (
        _cuantos(len(ids), "registro", "registros")
        if que == REGISTROS
        else _cuantos(len(ids), "pendiente", "pendientes")
    )
    texto = _lista(f"⚠️ *VOY A BORRAR {cosa.upper()}*", lineas)
    borrarlo = "borrarlo" if len(registros) + len(pendientes) == 1 else "borrarlos"
    texto.append(
        f"\n{LINEA}\n¿Confirmás? Respondé *sí* para {borrarlo} o *no* para cancelar.\n_Esto no se puede deshacer._"
    )
    return "\n".join(texto)


def pedir_correccion(
    cuaderno: Cuaderno, ids: list[int], lineas: list[str], cambios: dict[str, Any], resumen: str, ahora: datetime
) -> str:
    """Deja la corrección de esos pendientes esperando el *sí*. `cambios`: lo que recibe
    `Cuaderno.corregir_pendientes` (la fecha como texto ISO, el campo por su id)."""
    cuaderno.guardar_borrado_pendiente(ids, ahora, CORREGIR, cambios)
    texto = _lista(f"✏️ *VOY A CORREGIR {len(ids)} PENDIENTES*", lineas)
    texto.append(f"\n{resumen}\n\n{LINEA}\n¿Confirmás? Respondé *sí* para corregirlos o *no* para cancelar.")
    return "\n".join(texto)


def _respondido(cuaderno: Cuaderno) -> dict[str, Any]:
    """Lo que la persona ya respondió en este pedido (campos parecidos y fechas dudosas), para
    guardarlo junto con el pedido mientras espera otra respuesta."""
    return {
        "alias": cuaderno.alias,
        "permitidos": sorted(cuaderno.permitidos),
        "fechas": cuaderno.fechas,
        "alias_lotes": cuaderno.alias_lotes,
    }


def _recuperar(cuaderno: Cuaderno, datos: dict[str, Any]) -> None:
    cuaderno.alias = {k: int(v) for k, v in datos.get("alias", {}).items()}
    cuaderno.permitidos = set(datos.get("permitidos", []))
    cuaderno.fechas = {k: str(v) for k, v in datos.get("fechas", {}).items()}
    cuaderno.alias_lotes = {k: int(v) for k, v in datos.get("alias_lotes", {}).items()}


def preguntar_campo(
    cuaderno: Cuaderno, nuevo: str, existente: Establecimiento, pedidos: list[dict[str, Any]], ahora: datetime
) -> str:
    """¿El campo nuevo es uno que ya tiene? Guarda el pedido entero para hacerlo después de la
    respuesta, con lo que ya se respondió antes en el mismo pedido."""
    datos = {"pedidos": pedidos, "nuevo": nuevo, "existente": existente.id, **_respondido(cuaderno)}
    cuaderno.guardar_borrado_pendiente([], ahora, CAMPO, datos)
    return (
        f"🤔 *¿{nuevo} es {existente.nombre}?*\n\n"
        f"Ya tenés cargado el campo *{existente.nombre}*.\n\n{LINEA}\n"
        f"Respondé *sí* para anotarlo en {existente.nombre}, *no* para crear el campo *{nuevo}*, "
        f"*cambiale el nombre* para que {existente.nombre} pase a llamarse {nuevo}, o *cancelá*."
    )


def preguntar_parecido(
    cuaderno: Cuaderno, parecido: NombreParecido, pedidos: list[dict[str, Any]], ahora: datetime
) -> str:
    """¿Es ese? Se nombró un campo o un lote que no existe y hay uno parecido. Guarda el pedido
    entero para hacerlo después del *sí*, como con un campo parecido al anotar."""
    existente = parecido.existente
    es_lote = isinstance(existente, Lote)
    nombre = nombre_lote(existente.nombre) if es_lote else existente.nombre
    datos = {
        "pedidos": pedidos,
        "nombre": parecido.nombre,
        "existente": existente.id,
        "lote": es_lote,
        **_respondido(cuaderno),
    }
    cuaderno.guardar_borrado_pendiente([], ahora, PARECIDO, datos)
    if es_lote:
        donde = f"*{parecido.donde}*" if parecido.donde else "tus lotes sin campo"
        titulo, falta = f"¿Es el {nombre}?", f"No encontré el *{parecido.nombre}* en {donde}, pero sí el *{nombre}*."
    else:
        titulo, falta = f"¿Es {nombre}?", f"No tenés ningún campo que se llame *{parecido.nombre}*, pero sí *{nombre}*."
    return f"🤔 *{titulo}*\n\n{falta}\n\n{LINEA}\nRespondé *sí* para seguir con {nombre} o *no* para cancelar."


def pedir_union(cuaderno: Cuaderno, que: str, origen: int, destino: int, texto: str, ahora: datetime) -> str:
    """Deja la unión de dos campos (`UNIR_CAMPOS`) o dos lotes (`UNIR_LOTES`) esperando el
    *sí*. `texto`: la pregunta, con lo que pasa al que queda."""
    cuaderno.guardar_borrado_pendiente([origen, destino], ahora, que)
    return f"{texto}\n\n{LINEA}\n¿Confirmás? Respondé *sí* para unirlos o *no* para cancelar."


def pedir_baja(cuaderno: Cuaderno, que: str, id_: int, texto: str, ahora: datetime) -> str:
    """Deja el borrado de un campo (`BORRAR_CAMPO`) o un lote (`BORRAR_LOTE`) esperando el
    *sí*. `texto`: la pregunta, con lo que se borra."""
    cuaderno.guardar_borrado_pendiente([id_], ahora, que)
    return (
        f"{texto}\n\n{LINEA}\n¿Confirmás? Respondé *sí* para borrarlo o *no* para cancelar.\n"
        "_Esto no se puede deshacer._"
    )


def preguntar_fecha(
    cuaderno: Cuaderno, clave: str, opciones: tuple[date, date], pedidos: list[dict[str, Any]], ahora: datetime
) -> str:
    """¿Para cuándo? El día de la semana y el número no coinciden: la primera opción es la
    fecha por el número y la segunda, el día de la semana más cercano. Guarda el pedido entero."""
    datos = {"pedidos": pedidos, "clave": clave, "opciones": [o.isoformat() for o in opciones], **_respondido(cuaderno)}
    cuaderno.guardar_borrado_pendiente([], ahora, FECHA, datos)
    por_numero, por_dia = opciones
    return (
        f"🤔 *¿Para cuándo?*\n\nEl {por_numero:%d/%m} es {formato.dia_semana(por_numero)}, "
        f"no {formato.dia_semana(por_dia)}.\n\n"
        f"{SANGRIA}1️⃣ {formato.fecha_corta(por_numero)}\n{SANGRIA}2️⃣ {formato.fecha_corta(por_dia)}\n\n{LINEA}\n"
        "Respondé *1* o *2*, o *cancelá*."
    )


def _vigente(pendiente: BorradoPendiente, ahora: datetime) -> bool:
    creado = pendiente.creado if pendiente.creado.tzinfo else pendiente.creado.replace(tzinfo=UTC)
    return ahora - creado <= timedelta(minutes=CONFIRMAR_MINUTOS)


def resolver(ctx: Contexto, rehacer: Callable[[list[dict[str, Any]]], str]) -> str | None:
    """Si hay una pregunta esperando: la respuesta fija la resuelve y cualquier otro mensaje
    la descarta (None: sigue el flujo normal, con la pregunta como contexto para la IA).
    `rehacer`: ejecuta otra vez los pedidos guardados de un campo parecido."""
    cuaderno = ctx.cuaderno
    pendiente = cuaderno.tomar_borrado_pendiente()
    if pendiente is None:
        return None
    if pendiente.que == CAMPO:
        return _resolver_campo(ctx, pendiente, rehacer)
    if pendiente.que == FECHA:
        return _resolver_fecha(ctx, pendiente, rehacer)
    if pendiente.que == PARECIDO:
        return _resolver_parecido(ctx, pendiente, rehacer)
    if pendiente.que in (UNIR_CAMPOS, UNIR_LOTES):
        pregunta = preguntas.UNIR
    else:
        pregunta = preguntas.CORREGIR if pendiente.que == CORREGIR else preguntas.BORRAR
    if respuestas.es_no(ctx.texto):
        return preguntas.al_cancelar(pregunta)
    if not respuestas.es_si(ctx.texto):
        ctx.pregunta_abierta = pregunta
        return None
    if not _vigente(pendiente, ctx.ahora):
        return PASO_EL_TIEMPO.format(hice="borré nada" if pregunta == preguntas.BORRAR else "cambié nada")
    if pregunta == preguntas.UNIR:
        return _unir(ctx, pendiente)
    if pendiente.que in (BORRAR_CAMPO, BORRAR_LOTE):
        return _dar_de_baja(ctx, pendiente)
    if pendiente.que == CORREGIR:
        return _corregir(cuaderno, pendiente)
    return _borrar(cuaderno, pendiente)


def _borrar(cuaderno: Cuaderno, pendiente: BorradoPendiente) -> str:
    registros, pendientes = _a_borrar(pendiente)
    hechos = []
    if registros:
        hechos.append(_cuantos(cuaderno.borrar(registros), "registro", "registros"))
    if pendientes:
        borrados = cuaderno.borrar_pendientes(pendientes)
        hechos.append(_cuantos(borrados, "pendiente", "pendientes"))
        if not registros:
            titulo = "🗑️ *PENDIENTE BORRADO*" if borrados == 1 else "🗑️ *PENDIENTES BORRADOS*"
            return f"{titulo}\n\nListo, borré {hechos[0]}."
    return f"🗑️ *BORRADO*\n\nListo, borré {' y '.join(hechos)}."


def _corregir(cuaderno: Cuaderno, pendiente: BorradoPendiente) -> str:
    cambios = dict(pendiente.datos or {})
    vence = cambios.pop("vence", None)
    corregidos = cuaderno.corregir_pendientes(
        pendiente.ids, vence=date.fromisoformat(vence) if vence else None, **cambios
    )
    return f"✏️ *PENDIENTES CORREGIDOS*\n\nListo, corregí {len(corregidos)} pendientes."


def nombre_lote(nombre: str) -> str:
    """'3' -> 'lote 3'; 'potrero grande' queda igual."""
    return f"lote {nombre}" if nombre.isdecimal() else nombre


def resumen_union(contenido: Contenido, de_campo: bool) -> str:
    """Lo que pasa al que queda, una línea por cosa ("12 registros", "2 pendientes"...)."""
    cosas = [
        (contenido.registros, "registro", "registros"),
        (contenido.pendientes, "pendiente", "pendientes"),
        (len(contenido.lotes) if de_campo else 0, "lote", "lotes"),
        (contenido.sesiones, "sesión de trabajo", "sesiones de trabajo"),
    ]
    lineas = [f"{SANGRIA}› {n} {uno if n == 1 else varios}" for n, uno, varios in cosas if n]
    return "\n".join(lineas) or f"{SANGRIA}› nada anotado, solo el nombre"


def _dar_de_baja(ctx: Contexto, pendiente: BorradoPendiente) -> str:
    cuaderno = ctx.cuaderno
    if pendiente.que == BORRAR_CAMPO:
        campo = cuaderno.db.get(Establecimiento, pendiente.ids[0])
        nombre, de_campo, titulo = (campo.nombre if campo else None), True, "🗑️ *CAMPO BORRADO*"
        contenido = cuaderno.borrar_establecimiento(pendiente.ids[0])
    else:
        lote = cuaderno.db.get(Lote, pendiente.ids[0])
        nombre, de_campo, titulo = (nombre_lote(lote.nombre) if lote else None), False, "🗑️ *LOTE BORRADO*"
        contenido = cuaderno.borrar_lote(pendiente.ids[0])
    if contenido is None or nombre is None:
        return "🤔 No pude borrarlo: ya no está.\nMandá *mis campos* para ver cómo quedaron."
    return f"{titulo}\n\nListo, borré *{nombre}* con todo lo suyo:\n\n{resumen_union(contenido, de_campo)}"


def _unir(ctx: Contexto, pendiente: BorradoPendiente) -> str:
    origen_id, destino_id = pendiente.ids
    cuaderno = ctx.cuaderno
    if pendiente.que == UNIR_CAMPOS:
        origen, destino = cuaderno.db.get(Establecimiento, origen_id), cuaderno.db.get(Establecimiento, destino_id)
        nombres = (origen.nombre, destino.nombre) if origen and destino else None
        contenido = cuaderno.unir_establecimientos(origen_id, destino_id)
        titulo = "🔗 *CAMPOS UNIDOS*"
        de_campo = True
    else:
        lote_o, lote_d = cuaderno.db.get(Lote, origen_id), cuaderno.db.get(Lote, destino_id)
        nombres = (nombre_lote(lote_o.nombre), nombre_lote(lote_d.nombre)) if lote_o and lote_d else None
        contenido = cuaderno.unir_lotes(origen_id, destino_id)
        titulo = "🔗 *LOTES UNIDOS*"
        de_campo = False
    if contenido is None or nombres is None:
        return "🤔 No pude unirlos: uno de los dos ya no está.\nMandá *mis campos* para ver cómo quedaron."
    return (
        f"{titulo}\n\nListo: lo de *{nombres[0]}* pasó a *{nombres[1]}*.\n\n{resumen_union(contenido, de_campo)}\n\n"
        f"_{nombres[0]} ya no está en tus campos._"
        if de_campo
        else f"{titulo}\n\nListo: lo del *{nombres[0]}* pasó al *{nombres[1]}*.\n\n{resumen_union(contenido, de_campo)}"
    )


def _resolver_campo(
    ctx: Contexto, pendiente: BorradoPendiente, rehacer: Callable[[list[dict[str, Any]]], str]
) -> str | None:
    texto = ctx.texto
    datos = pendiente.datos or {}
    existente = ctx.cuaderno.db.get(Establecimiento, int(datos["existente"]))
    if respuestas.es_cancelar(texto):
        return preguntas.al_cancelar(preguntas.CAMPO)
    renombrar = existente is not None and respuestas.es_renombrar(texto, [datos["nuevo"], existente.nombre])
    es_el_mismo = renombrar or respuestas.es_si(texto)
    if not es_el_mismo and not respuestas.es_no(texto):
        ctx.pregunta_abierta = preguntas.CAMPO
        return None
    if not _vigente(pendiente, ctx.ahora):
        return PASO_EL_TIEMPO.format(hice="anoté nada")
    clave = clave_establecimiento(datos["nuevo"]) or ""
    _recuperar(ctx.cuaderno, datos)
    if renombrar and existente is not None and ctx.cuaderno.establecimiento_existente(datos["nuevo"]) is None:
        antes = existente.nombre
        ctx.cuaderno.renombrar_establecimiento(existente, datos["nuevo"])
        aviso = f"✏️ *{antes}* ahora se llama *{existente.nombre}*."
        return f"{aviso}\n\n{rehacer(datos['pedidos'])}"
    if es_el_mismo:
        ctx.cuaderno.alias[clave] = int(datos["existente"])
    else:
        ctx.cuaderno.permitidos.add(clave)
    return rehacer(datos["pedidos"])


def _resolver_parecido(
    ctx: Contexto, pendiente: BorradoPendiente, rehacer: Callable[[list[dict[str, Any]]], str]
) -> str | None:
    texto = ctx.texto
    if respuestas.es_no(texto) or respuestas.es_cancelar(texto):
        return preguntas.al_cancelar(preguntas.PARECIDO)
    if not respuestas.es_si(texto):
        ctx.pregunta_abierta = preguntas.PARECIDO
        return None
    if not _vigente(pendiente, ctx.ahora):
        return PASO_EL_TIEMPO.format(hice="cambié nada")
    datos = pendiente.datos or {}
    _recuperar(ctx.cuaderno, datos)
    if datos["lote"]:
        ctx.cuaderno.alias_lotes[normalizar_lote(datos["nombre"]) or ""] = int(datos["existente"])
    else:
        ctx.cuaderno.alias[clave_establecimiento(datos["nombre"]) or ""] = int(datos["existente"])
    return rehacer(datos["pedidos"])


def _resolver_fecha(
    ctx: Contexto, pendiente: BorradoPendiente, rehacer: Callable[[list[dict[str, Any]]], str]
) -> str | None:
    texto = ctx.texto
    if respuestas.es_no(texto):
        return preguntas.al_cancelar(preguntas.FECHA)
    datos = pendiente.datos or {}
    opciones = [date.fromisoformat(o) for o in datos["opciones"]]
    elegida = respuestas.cual_fecha(texto, opciones)
    if elegida is None:
        ctx.pregunta_abierta = preguntas.FECHA
        return None
    if not _vigente(pendiente, ctx.ahora):
        return PASO_EL_TIEMPO.format(hice="anoté nada")
    _recuperar(ctx.cuaderno, datos)
    ctx.cuaderno.fechas[datos["clave"]] = opciones[elegida].isoformat()
    return rehacer(datos["pedidos"])
