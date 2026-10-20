"""Mis campos: los establecimientos y lotes de la persona, con cuántos registros tiene cada uno.

"mis campos" es un atajo sin IA; pedido con otras palabras ("¿qué campos tengo cargados?")
llega por la IA a la misma función (cuenta.py). Renombrar y unir campos y lotes está en
renombrar.py.
"""

from app.infra.modelos import Usuario
from app.nucleo.cuaderno import Campo, Cuaderno
from app.salidas.whatsapp import SANGRIA
from app.salidas.whatsapp import SEPARADOR as LINEA

PEDIR = {"mis campos", "mis establecimientos", "mis lotes"}

SIN_CAMPOS = (
    "📭 Todavía no anotaste nada en ningún campo.\n\n"
    "Decime dónde estás y lo que anotes queda ahí, por ejemplo: _estoy en La Esperanza_."
)


def _registros(cantidad: int) -> str:
    return f"{cantidad} registro{'s' if cantidad != 1 else ''}"


def _pendientes(cantidad: int) -> str:
    return f" · {cantidad} pendiente{'s' if cantidad != 1 else ''}" if cantidad else ""


def _bloque(campo: Campo, actual: int | None) -> str:
    cuantos = f"{_registros(campo.registros)}{_pendientes(campo.pendientes)}"
    if campo.establecimiento is None:
        titulo = f"_Sin establecimiento_ · {cuantos}"
    else:
        aca = " · _estás acá_" if campo.establecimiento.id == actual else ""
        titulo = f"📍 *{campo.establecimiento.nombre}* · {cuantos}{aca}"
    if not campo.lotes:
        return titulo
    return f"{titulo}\n{SANGRIA}Lotes: {', '.join(campo.lotes)}"


def mis_campos(cuaderno: Cuaderno, usuario: Usuario) -> str:
    campos = cuaderno.campos()
    if not campos:
        return SIN_CAMPOS
    bloques = "\n\n".join(_bloque(c, usuario.establecimiento_actual_id) for c in campos)
    return (
        f"🏡 *MIS CAMPOS*\n\n{bloques}\n\n{LINEA}\n"
        "_Para ver lo anotado en uno: ¿qué tengo anotado en La Esperanza?_\n"
        "_Para cambiar de campo: estoy en El Ombú._\n"
        "_Para cambiarle el nombre: Omu en realidad es El Ombú._"
    )
