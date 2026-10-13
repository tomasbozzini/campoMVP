"""Borrar: deshacer lo último que se anotó, o borrar los registros que la persona describe.

Cada descripción tiene que señalar UN solo registro. Si coincide con varios, no se borra
nada de esa descripción y se muestran las opciones para que precise, salvo que haya
pedido explícitamente borrar todos ("todas las lluvias de La Pastora"). Si en total se
van a borrar muchos registros, se pide confirmación antes.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from pydantic import BeforeValidator

from app.ia.esquemas import Bandera, Esquema, EsquemaAccion
from app.infra.modelos import Evento
from app.modulos.comun.registros import Referencia, coincide, describir
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto
from app.nucleo.cuaderno import Cuaderno
from app.salidas import whatsapp as formato
from app.salidas.whatsapp import SEPARADOR as LINEA

# Cuántos registros se revisan para encontrar lo que se quiere borrar.
BORRADO_ULTIMOS = 5000
MAX_REFERENCIAS_BORRADO = 10

# Desde esta cantidad de registros de una vez se pide confirmación con "sí".
CONFIRMAR_DESDE = 4
CONFIRMAR_MINUTOS = 10
SI = {"si", "sí", "dale", "confirmo", "confirmar", "ok", "si, borralos", "sí, borralos", "si borralos", "sí borralos"}
NO = {"no", "cancelar", "cancela", "cancelá", "no, cancelar"}

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


def borrar_ultimo(cuaderno: Cuaderno) -> str:
    """Deshace lo último que se anotó: todos los registros de ese mensaje."""
    ultimo = cuaderno.ultimo()
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
        return borrar_ultimo(cuaderno)
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
    if len(a_borrar) >= CONFIRMAR_DESDE:
        cuaderno.guardar_borrado_pendiente(list(a_borrar), datetime.now(UTC))
        lista = list(a_borrar.values())
        lineas.append(f"⚠️ *VOY A BORRAR {len(lista)} REGISTROS*\n")
        lineas += [f"      › {formato.linea(e)}" for e in lista[:10]]
        if len(lista) > 10:
            lineas.append(f"      _...y {len(lista) - 10} más_")
        lineas.append(
            f"\n{LINEA}\n¿Confirmás? Respondé *sí* para borrarlos o *no* para cancelar.\n_Esto no se puede deshacer._"
        )
    elif a_borrar:
        lineas.append("🗑️ *BORRADO*\n")
        lineas.append(formato.tarjetas(list(a_borrar.values())))
        cuaderno.borrar(list(a_borrar))
    if avisos:
        if lineas:
            lineas.append("")
        lineas += avisos
    return "\n".join(lineas) or "🤔 No entendí qué querés borrar."


def resolver_pendiente(cuaderno: Cuaderno, comando: str) -> str | None:
    """Si hay un borrado esperando confirmación: "sí" lo hace, "no" lo cancela, y
    cualquier otro mensaje lo descarta (y sigue el flujo normal)."""
    pendiente = cuaderno.tomar_borrado_pendiente()
    if pendiente is None:
        return None
    creado = pendiente.creado if pendiente.creado.tzinfo else pendiente.creado.replace(tzinfo=UTC)
    vigente = datetime.now(UTC) - creado <= timedelta(minutes=CONFIRMAR_MINUTOS)
    if comando in NO:
        return "👌 Listo, no borré nada."
    if comando not in SI:
        return None
    if not vigente:
        return "⏱️ Pasó mucho tiempo desde que lo pediste y no borré nada.\nSi querés, pedilo de nuevo."
    return f"🗑️ *BORRADO*\n\nListo, borré {cuaderno.borrar(pendiente.ids)} registros."


ACCION = Accion("borrar", Borrar, manejar)
