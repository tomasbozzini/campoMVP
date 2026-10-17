"""Preguntas que esperan un *sí*: borrados grandes, correcciones de muchos pendientes y campos
parecidos a otro.

- Desde 4 registros o 4 pendientes de una vez, borrar o corregir pide confirmación.
- Antes de crear un campo con un nombre muy parecido a uno que ya existe ("Omu" y "El
  Ombú"), se pregunta si es el mismo. Lo del mensaje se hace después de la respuesta: *sí*
  lo anota en el que ya existe, *no* crea el nuevo, y "cancelá" o "dejá" no anota nada.

La pregunta queda esperando durante 10 minutos. *no* la cancela y se aceptan las variantes de
siempre ("dale", "sí, borrá", "no, dejá"): ver `nucleo/respuestas.py`. Cualquier otro mensaje
la descarta y va a la IA con la pregunta como contexto, por si la cancela con otras palabras.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.infra.modelos import BorradoPendiente, Establecimiento
from app.nucleo import preguntas, respuestas
from app.nucleo.contexto import Contexto
from app.nucleo.cuaderno import Cuaderno
from app.nucleo.normalizar import clave_establecimiento
from app.salidas.whatsapp import SANGRIA
from app.salidas.whatsapp import SEPARADOR as LINEA

CONFIRMAR_DESDE = 4
CONFIRMAR_MINUTOS = 10
MAX_EN_LISTA = 10

# Qué espera confirmación.
REGISTROS, PENDIENTES, CORREGIR, CAMPO = "registros", "pendientes", "corregir", "campo"

PASO_EL_TIEMPO = "⏱️ Pasó mucho tiempo desde que lo pediste y no {hice}.\nSi querés, pedilo de nuevo."


def _lista(titulo: str, lineas: list[str]) -> list[str]:
    texto = [f"{titulo}\n"]
    texto += [f"{SANGRIA}› {linea}" for linea in lineas[:MAX_EN_LISTA]]
    if len(lineas) > MAX_EN_LISTA:
        texto.append(f"{SANGRIA}_...y {len(lineas) - MAX_EN_LISTA} más_")
    return texto


def pedir(cuaderno: Cuaderno, que: str, ids: list[int], lineas: list[str], ahora: datetime) -> str:
    """Deja el borrado esperando el *sí* y muestra qué se va a borrar (`lineas`, una por cosa)."""
    cuaderno.guardar_borrado_pendiente(ids, ahora, que)
    texto = _lista(f"⚠️ *VOY A BORRAR {len(ids)} {que.upper()}*", lineas)
    texto.append(
        f"\n{LINEA}\n¿Confirmás? Respondé *sí* para borrarlos o *no* para cancelar.\n_Esto no se puede deshacer._"
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


def preguntar_campo(
    cuaderno: Cuaderno,
    nuevo: str,
    existente: Establecimiento,
    pedidos: list[dict[str, Any]],
    alias: dict[str, int],
    permitidos: list[str],
    ahora: datetime,
) -> str:
    """¿El campo nuevo es uno que ya tiene? Guarda el pedido entero para hacerlo después de la
    respuesta, con lo que ya se respondió antes en el mismo pedido (`alias`, `permitidos`)."""
    datos = {"pedidos": pedidos, "nuevo": nuevo, "existente": existente.id, "alias": alias, "permitidos": permitidos}
    cuaderno.guardar_borrado_pendiente([], ahora, CAMPO, datos)
    return (
        f"🤔 *¿{nuevo} es {existente.nombre}?*\n\n"
        f"Ya tenés cargado el campo *{existente.nombre}*.\n\n{LINEA}\n"
        f"Respondé *sí* para anotarlo en {existente.nombre}, *no* para crear el campo *{nuevo}*, o *cancelá*."
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
    pregunta = preguntas.CORREGIR if pendiente.que == CORREGIR else preguntas.BORRAR
    if respuestas.es_no(ctx.texto):
        return preguntas.al_cancelar(pregunta)
    if not respuestas.es_si(ctx.texto):
        ctx.pregunta_abierta = pregunta
        return None
    if not _vigente(pendiente, ctx.ahora):
        return PASO_EL_TIEMPO.format(hice="cambié nada" if pendiente.que == CORREGIR else "borré nada")
    if pendiente.que == CORREGIR:
        return _corregir(cuaderno, pendiente)
    if pendiente.que == PENDIENTES:
        return f"🗑️ *PENDIENTES BORRADOS*\n\nListo, borré {cuaderno.borrar_pendientes(pendiente.ids)} pendientes."
    return f"🗑️ *BORRADO*\n\nListo, borré {cuaderno.borrar(pendiente.ids)} registros."


def _corregir(cuaderno: Cuaderno, pendiente: BorradoPendiente) -> str:
    cambios = dict(pendiente.datos or {})
    vence = cambios.pop("vence", None)
    corregidos = cuaderno.corregir_pendientes(
        pendiente.ids, vence=date.fromisoformat(vence) if vence else None, **cambios
    )
    return f"✏️ *PENDIENTES CORREGIDOS*\n\nListo, corregí {len(corregidos)} pendientes."


def _resolver_campo(
    ctx: Contexto, pendiente: BorradoPendiente, rehacer: Callable[[list[dict[str, Any]]], str]
) -> str | None:
    texto = ctx.texto
    if respuestas.es_cancelar(texto):
        return preguntas.al_cancelar(preguntas.CAMPO)
    es_el_mismo = respuestas.es_si(texto)
    if not es_el_mismo and not respuestas.es_no(texto):
        ctx.pregunta_abierta = preguntas.CAMPO
        return None
    if not _vigente(pendiente, ctx.ahora):
        return PASO_EL_TIEMPO.format(hice="anoté nada")
    datos = pendiente.datos or {}
    clave = clave_establecimiento(datos["nuevo"]) or ""
    alias = {k: int(v) for k, v in datos.get("alias", {}).items()}
    permitidos = set(datos.get("permitidos", []))
    if es_el_mismo:
        alias[clave] = int(datos["existente"])
    else:
        permitidos.add(clave)
    ctx.cuaderno.alias, ctx.cuaderno.permitidos = alias, permitidos
    return rehacer(datos["pedidos"])
