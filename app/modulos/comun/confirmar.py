"""Borrados grandes: desde 4 registros o 4 pendientes de una vez se pide confirmación.

El borrado queda esperando un *sí* durante 10 minutos. *no* lo cancela y cualquier otro
mensaje lo descarta (y sigue su camino normal).
"""

from datetime import UTC, datetime, timedelta

from app.nucleo.cuaderno import Cuaderno
from app.salidas.whatsapp import SANGRIA
from app.salidas.whatsapp import SEPARADOR as LINEA

CONFIRMAR_DESDE = 4
CONFIRMAR_MINUTOS = 10
MAX_EN_LISTA = 10
SI = {"si", "sí", "dale", "confirmo", "confirmar", "ok", "si, borralos", "sí, borralos", "si borralos", "sí borralos"}
NO = {"no", "cancelar", "cancela", "cancelá", "no, cancelar"}

# Qué se va a borrar.
REGISTROS, PENDIENTES = "registros", "pendientes"


def pedir(cuaderno: Cuaderno, que: str, ids: list[int], lineas: list[str], ahora: datetime) -> str:
    """Deja el borrado esperando el *sí* y muestra qué se va a borrar (`lineas`, una por cosa)."""
    cuaderno.guardar_borrado_pendiente(ids, ahora, que)
    texto = [f"⚠️ *VOY A BORRAR {len(ids)} {que.upper()}*\n"]
    texto += [f"{SANGRIA}› {linea}" for linea in lineas[:MAX_EN_LISTA]]
    if len(lineas) > MAX_EN_LISTA:
        texto.append(f"{SANGRIA}_...y {len(lineas) - MAX_EN_LISTA} más_")
    texto.append(
        f"\n{LINEA}\n¿Confirmás? Respondé *sí* para borrarlos o *no* para cancelar.\n_Esto no se puede deshacer._"
    )
    return "\n".join(texto)


def resolver(cuaderno: Cuaderno, comando: str, ahora: datetime) -> str | None:
    """Si hay un borrado esperando confirmación: "sí" lo hace, "no" lo cancela, y
    cualquier otro mensaje lo descarta (y sigue el flujo normal)."""
    pendiente = cuaderno.tomar_borrado_pendiente()
    if pendiente is None:
        return None
    creado = pendiente.creado if pendiente.creado.tzinfo else pendiente.creado.replace(tzinfo=UTC)
    vigente = ahora - creado <= timedelta(minutes=CONFIRMAR_MINUTOS)
    if comando in NO:
        return "👌 Listo, no borré nada."
    if comando not in SI:
        return None
    if not vigente:
        return "⏱️ Pasó mucho tiempo desde que lo pediste y no borré nada.\nSi querés, pedilo de nuevo."
    if pendiente.que == PENDIENTES:
        return f"🗑️ *PENDIENTES BORRADOS*\n\nListo, borré {cuaderno.borrar_pendientes(pendiente.ids)} pendientes."
    return f"🗑️ *BORRADO*\n\nListo, borré {cuaderno.borrar(pendiente.ids)} registros."
