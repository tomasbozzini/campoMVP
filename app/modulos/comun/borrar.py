"""Borrar: deshacer lo último que se anotó, o borrar los registros que la persona describe.

Cada descripción tiene que señalar UN solo registro. Si coincide con varios, no se borra
nada de esa descripción y se muestran las opciones para que precise, salvo que haya
pedido explícitamente borrar todos ("todas las lluvias de La Pastora"). Si en total se
van a borrar muchos registros, se pide confirmación antes.
"""

from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import BeforeValidator

from app.ia.esquemas import Bandera, Esquema, EsquemaAccion
from app.infra.modelos import Evento
from app.modulos.comun import confirmar, pendientes
from app.modulos.comun.registros import Referencia, coincide, describir
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto
from app.nucleo.cuaderno import Cuaderno
from app.salidas import whatsapp as formato

# Cuántos registros se revisan para encontrar lo que se quiere borrar.
BORRADO_ULTIMOS = 5000
MAX_REFERENCIAS_BORRADO = 10

NADA_ANOTADO = "📭 No tenés nada anotado para borrar."


class ReferenciaBorrado(Referencia):
    # True SOLO si pide explícitamente borrar todos los que coincidan.
    todos: Bandera = False


def _referencias(valor: object) -> object:
    """[] o algo que no es una lista: "borrá lo último". Si no, hasta 10 descripciones
    (las que no son objetos se descartan)."""
    if not isinstance(valor, list) or not valor:
        return None
    return [r for r in valor[:MAX_REFERENCIAS_BORRADO] if isinstance(r, dict)]


class DatosBorrado(Esquema):
    # None: borrar lo último que se anotó.
    registros: Annotated[list[ReferenciaBorrado] | None, BeforeValidator(_referencias)] = None


class Borrar(EsquemaAccion):
    borrado: DatosBorrado


def _con_zona(momento: datetime) -> datetime:
    """SQLite devuelve las fechas sin zona: son UTC."""
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def borrar_ultimo(cuaderno: Cuaderno, hoy: date) -> str:
    """Deshace lo último que se anotó: todos los registros de ese mensaje, o un pendiente."""
    ultimo = cuaderno.ultimo()
    pendiente = cuaderno.ultimo_pendiente()
    if pendiente is not None and (ultimo is None or _con_zona(pendiente.creado) > _con_zona(ultimo.creado)):
        texto = pendientes.tarjeta(pendiente, hoy, icono="🗑️")
        cuaderno.borrar_pendientes([pendiente.id])
        return "🗑️ *PENDIENTE BORRADO*\n\n" + texto
    if ultimo is None:
        return NADA_ANOTADO
    # Por mensaje_id y no por fecha: dos mensajes seguidos pueden caer en el mismo
    # timestamp (en Windows el reloj salta cada ~15 ms) y se borraban los dos.
    # Los registros anteriores a la columna no tienen id: se borra solo ese, porque un
    # "mensaje_id IS NULL" borraría todos los viejos de una.
    borrados = [ultimo] if ultimo.mensaje_id is None else cuaderno.del_mensaje(ultimo.mensaje_id)
    texto = formato.tarjetas(borrados)
    cuaderno.borrar([e.id for e in borrados])
    return "🗑️ *BORRADO*\n\n" + texto


def manejar(ctx: Contexto, datos: Borrar) -> str:
    cuaderno = ctx.cuaderno
    referencias = datos.borrado.registros
    if referencias is None:
        return borrar_ultimo(cuaderno, ctx.hoy)
    recientes = cuaderno.recientes(BORRADO_ULTIMOS)

    a_borrar: dict[int, Evento] = {}
    avisos: list[str] = []
    for ref in referencias:
        if not ref.tiene_datos() and not ref.todos:
            avisos.append("🤔 Una de las cosas que pediste borrar no la pude identificar.")
            continue
        # Sin datos y con "todos": es todo el cuaderno (siempre pide confirmación).
        coinciden = [e for e in recientes if coincide(e, ref)] if ref.tiene_datos() else list(recientes)
        if not coinciden:
            avisos.append(f"🔍 No encontré: {describir(ref)}." if ref.tiene_datos() else "📭 No tenés nada anotado.")
        elif len(coinciden) > 1 and not ref.todos:
            opciones = "\n".join(f"      › {formato.linea(e)}" for e in coinciden[:8])
            mas = f"\n      _...y {len(coinciden) - 8} más_" if len(coinciden) > 8 else ""
            avisos.append(
                f"🤔 *Hay {len(coinciden)} registros* que coinciden con {describir(ref)}.\n"
                f"No borré ninguno:\n\n{opciones}{mas}\n\n"
                "Decime cuál (con la fecha, el lote o el campo), o pedí borrar *todos*."
            )
        else:
            a_borrar.update({e.id: e for e in coinciden})

    lineas = []
    if len(a_borrar) >= confirmar.CONFIRMAR_DESDE:
        lista = [formato.linea(e) for e in a_borrar.values()]
        lineas.append(confirmar.pedir(cuaderno, confirmar.REGISTROS, list(a_borrar), lista, ctx.ahora))
    elif a_borrar:
        lineas.append("🗑️ *BORRADO*\n")
        lineas.append(formato.tarjetas(list(a_borrar.values())))
        cuaderno.borrar(list(a_borrar))
    if avisos:
        if lineas:
            lineas.append("")
        lineas += avisos
    return "\n".join(lineas) or "🤔 No entendí qué querés borrar."


ACCION = Accion("borrar", Borrar, manejar)
