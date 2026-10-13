"""Consultar: buscar en el cuaderno propio y mostrar los registros con sus totales.

Las cuentas las hace el código: la IA solo arma los filtros y nunca ve los datos.
"""

from collections import defaultdict
from typing import Annotated

from app.ia.esquemas import Esquema, EsquemaAccion, Fecha, texto
from app.infra.modelos import Evento
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


def totales(eventos: list[Evento]) -> tuple[dict[str, int], dict[tuple[str, str], float]]:
    """Animales por tipo de evento y suma de valores por (tipo, unidad)."""
    animales: dict[str, int] = defaultdict(int)
    valores: dict[tuple[str, str], float] = defaultdict(float)
    for e in eventos:
        if e.cantidad_animales:
            animales[e.tipo] += e.cantidad_animales
        if e.valor is not None and e.unidad:
            valores[(e.tipo, e.unidad)] += e.valor
    return dict(animales), dict(valores)


def manejar(ctx: Contexto, datos: Consultar) -> str:
    f = datos.consulta
    eventos = ctx.cuaderno.buscar(
        Filtros(
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
    )
    if not eventos:
        return SIN_RESULTADOS

    lugares = {e.establecimiento for e in eventos}
    subtitulo = [f"📍 {eventos[0].establecimiento}"] if len(lugares) == 1 and eventos[0].establecimiento else []
    subtitulo.append(f"{len(eventos)} registro{'s' if len(eventos) != 1 else ''}")
    partes = ["📋 *TUS REGISTROS*\n" + " · ".join(subtitulo)]

    animales, valores = totales(eventos)
    if animales or valores:
        filas = [f"      {formato.icono(t)} {formato.nombre_tipo(t)}: *{c}* animales" for t, c in animales.items()]
        filas += [
            f"      {formato.icono(t)} {formato.nombre_tipo(t)}: *{formato.numero(v)} {u}*"
            for (t, u), v in valores.items()
        ]
        partes.append("📊 *Totales*\n" + "\n".join(filas))

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
