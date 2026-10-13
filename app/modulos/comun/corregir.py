"""Corregir: cambiar o completar un registro que la persona ya anotó."""

from typing import Annotated

from pydantic import Field

from app.ia.esquemas import Esquema, EsquemaAccion, SiNoVacio, texto
from app.modulos.comun.registros import DatosEvento, Referencia, coincide, fecha_valida
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto
from app.nucleo.normalizar import clave_establecimiento
from app.salidas import whatsapp as formato
from app.salidas.whatsapp import SEPARADOR as LINEA

# Cuántos registros recientes se revisan para encontrar el que se quiere corregir.
CORRECCION_ULTIMOS = 20

NO_ENCONTRADO = (
    "🤔 No encontré cuál de tus registros querés corregir.\n"
    "Con *¿qué tengo anotado?* ves la lista, o mandá *borrar* y anotalo de nuevo."
)
SIN_CAMBIOS = "🤔 No entendí qué querés cambiar.\nProbá con algo como: _eran 30, no 20_"


class Cambios(DatosEvento):
    """Solo lo que cambia. La categoría y la confianza no se corrigen."""

    establecimiento: Annotated[str | None, texto(120)] = None


# Lo que se puede corregir de un registro (la categoría y la confianza no).
CORREGIBLES = [c for c in Cambios.model_fields if c not in ("categoria", "confianza")]


class Correccion(Esquema):
    # Vacía si dice "lo último", "lo de recién": se corrige el último registro.
    referencia: Annotated[Referencia, SiNoVacio] = Field(default_factory=Referencia)
    cambios: Annotated[Cambios, SiNoVacio] = Field(default_factory=Cambios)


class Corregir(EsquemaAccion):
    correccion: Correccion


def manejar(ctx: Contexto, datos: Corregir) -> str:
    referencia, cambios = datos.correccion.referencia, datos.correccion.cambios
    recientes = ctx.cuaderno.recientes(CORRECCION_ULTIMOS)
    evento = next((e for e in recientes if coincide(e, referencia)), None)
    if evento is None:
        return NO_ENCONTRADO

    antes = formato.foto(evento)
    aplicados = 0
    for campo in CORREGIBLES:
        valor = getattr(cambios, campo)
        if valor is None:
            continue
        if campo == "establecimiento":
            evento.establecimiento = valor
            evento.establecimiento_clave = clave_establecimiento(valor)
        elif campo == "fecha_evento":
            evento.fecha_evento = fecha_valida(valor, ctx.hoy)
        else:
            setattr(evento, campo, valor)
        aplicados += 1
    if not aplicados:
        return SIN_CAMBIOS

    ctx.db.flush()
    cambios_hechos = formato.cambios(antes, evento)
    if not cambios_hechos:
        return "👌 Ese registro ya tenía esos datos, no cambié nada.\n\n" + formato.tarjeta(evento)
    return "\n\n".join(
        [
            "✏️ *CORREGIDO*",
            "\n".join(cambios_hechos),
            "*Así quedó:*\n" + formato.tarjeta(evento),
            f"{LINEA}\n_¿Algo mal? Corregilo de nuevo o mandá *borrar*._",
        ]
    )


ACCION = Accion("corregir", Corregir, manejar)
