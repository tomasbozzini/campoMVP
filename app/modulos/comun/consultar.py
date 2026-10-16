"""Consultar: buscar en el cuaderno propio y mostrar los registros con sus totales.

Las cuentas las hace el código: la IA solo arma los filtros y nunca ve los datos.
"""

from typing import Annotated

from app.ia.esquemas import Esquema, EsquemaAccion, Fecha, texto
from app.modulos.comun.registros import Lote
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto
from app.nucleo.cuaderno import Filtros
from app.nucleo.normalizar import clave_establecimiento
from app.salidas import whatsapp as formato
from app.salidas.whatsapp import SEPARADOR as LINEA

MAX_LINEAS_CONSULTA = 15
SIN_RESULTADOS = "🔍 No encontré registros para esa consulta."


class FiltrosConsulta(Esquema):
    """Si pide "todo lo anotado", vienen todos vacíos."""

    categoria: Annotated[str | None, texto(20)] = None
    tipo: Annotated[str | None, texto(30)] = None
    lote: Lote = None
    caravana: Annotated[str | None, texto(40)] = None
    categoria_animal: Annotated[str | None, texto(40)] = None
    producto: Annotated[str | None, texto(120)] = None
    establecimiento: Annotated[str | None, texto(120)] = None
    desde: Fecha = None
    hasta: Fecha = None


class Consultar(EsquemaAccion):
    consulta: FiltrosConsulta


def filtros(f: FiltrosConsulta) -> Filtros:
    """Los filtros del cuaderno a partir de lo que pidió la IA (también para los archivos)."""
    return Filtros(
        establecimiento_clave=clave_establecimiento(f.establecimiento),
        categoria=f.categoria,
        tipo=f.tipo,
        lote=f.lote,
        caravana=f.caravana,
        categoria_animal=f.categoria_animal,
        producto=f.producto,
        desde=f.desde,
        hasta=f.hasta,
    )


def manejar(ctx: Contexto, datos: Consultar) -> str:
    eventos = ctx.cuaderno.buscar(filtros(datos.consulta))
    if not eventos:
        return SIN_RESULTADOS

    lugares = {e.establecimiento_id for e in eventos}
    unico = eventos[0].nombre_establecimiento if len(lugares) == 1 else None
    subtitulo = [f"📍 {unico}"] if unico else []
    subtitulo.append(f"{len(eventos)} registro{'s' if len(eventos) != 1 else ''}")
    partes = ["📋 *TUS REGISTROS*\n" + " · ".join(subtitulo)]

    if bloque := formato.totales(eventos):
        partes.append(bloque)

    partes.append(LINEA)
    mostrados = eventos[:MAX_LINEAS_CONSULTA]
    # Si todos son del mismo lugar, ya figura arriba: no se repite en cada registro.
    partes.append(formato.por_dia(mostrados, lugar=len(lugares) > 1))
    if len(eventos) > MAX_LINEAS_CONSULTA:
        partes.append(
            f"_...y {len(eventos) - MAX_LINEAS_CONSULTA} más. Pedí un período, lote o campo más chico para verlos._"
        )
    return "\n\n".join(partes)


ACCION = Accion("consultar", Consultar, manejar)
