"""Exportar: los registros que pide la persona en un archivo, que le llega por WhatsApp.

"mandame un PDF de lo que hice en La Pastora este mes": la IA arma los mismos filtros que
en una consulta y el formato; el código busca, suma y arma el archivo. Decisión de producto
"Salidas": PDF si no dice otra cosa; "Excel" o "planilla" -> .xlsx; CSV solo si lo pide. El
PDF y el Excel llevan el membrete del profesional (nombre, rubro, localidad y matrícula) y
el pie legal. En esta etapa le llega solo al profesional, que lo reenvía.
"""

from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field

from app.ia.esquemas import Esquema, EsquemaAccion, SiNoVacio
from app.infra.config import config
from app.infra.marca import NOMBRE
from app.infra.modelos import Evento, Usuario
from app.modulos.comun.consultar import FiltrosConsulta, filtros
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Adjunto, Contexto
from app.nucleo.perfil import RUBROS
from app.salidas import pdf, planilla
from app.salidas import whatsapp as formato
from app.salidas.whatsapp import SEPARADOR as LINEA

PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# WhatsApp no acepta text/csv como documento: va como texto plano, con su nombre .csv.
CSV = "text/plain"
SIN_RESULTADOS = "🔍 No encontré registros para armar el archivo.\nProbá con otro período, lote o campo."

Formato = Literal["pdf", "excel", "csv"]

# El PDF propio de los registros de un tipo ("Registro de raspajes"): tipo -> (nombre del
# archivo, función que lo arma o devuelve None para el de siempre). Lo registra el módulo al cargarse.
PDFS: dict[str, tuple[str, Callable[[Contexto, FiltrosConsulta, list[Evento]], bytes | None]]] = {}


def _formato(valor: object) -> str:
    """Lo que no se entiende es PDF: es lo que se manda si no dice el formato."""
    return valor if valor in ("pdf", "excel", "csv") else "pdf"


class DatosExportar(Esquema):
    formato: Annotated[Formato, BeforeValidator(_formato)] = "pdf"


class Exportar(EsquemaAccion):
    exportar: Annotated[DatosExportar, SiNoVacio] = Field(default_factory=DatosExportar)
    consulta: Annotated[FiltrosConsulta, SiNoVacio] = Field(default_factory=FiltrosConsulta)


def _fecha(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def descripcion(f: FiltrosConsulta, eventos: list[Evento]) -> list[str]:
    """De qué es el archivo: "Campo: La Pastora", "Del 01/10/2026 al 16/10/2026", "12 registros"."""
    partes = []
    campos = {e.nombre_establecimiento for e in eventos}
    if f.establecimiento:
        partes.append(f"Campo: {next(iter(campos)) if len(campos) == 1 and None not in campos else f.establecimiento}")
    if f.lote:
        partes.append(f"Lote {f.lote}")
    if f.tipo:
        partes.append(formato.nombre_tipo(f.tipo))
    elif f.categoria:
        partes.append(f.categoria.capitalize())
    for valor in (f.producto, f.categoria_animal):
        if valor:
            partes.append(valor)
    if f.caravana:
        partes.append(f"Caravana {f.caravana}")
    if f.desde and f.hasta:
        partes.append(f"Del {_fecha(f.desde)} al {_fecha(f.hasta)}")
    elif f.desde:
        partes.append(f"Desde el {_fecha(f.desde)}")
    elif f.hasta:
        partes.append(f"Hasta el {_fecha(f.hasta)}")
    if not partes:
        partes.append("Todo lo anotado")
    partes.append(f"{len(eventos)} registro{'s' if len(eventos) != 1 else ''}")
    return partes


def resumen(eventos: list[Evento]) -> list[str]:
    """Los totales, sin el formato de WhatsApp: "Vacunación: 50 animales", "Lluvia: 35 mm"."""
    return [
        f"{formato.nombre_tipo(t)}: {c} animales"
        if u == "animales"
        else f"{formato.nombre_tipo(t)}: {formato.numero(c)} {u}"
        for t, c, u in formato.sumas(eventos)
    ]


def filas(eventos: list[Evento]) -> list[list[str]]:
    """Una fila por registro, del más viejo al más nuevo: fecha, campo, registro y detalle."""
    ordenados = sorted(eventos, key=lambda e: (e.fecha_evento, e.id))
    return [
        [
            _fecha(e.fecha_evento),
            e.nombre_establecimiento or "-",
            formato.nombre_tipo(e.tipo) + (f" · {e.producto}" if e.producto else ""),
            formato.detalle(e),
        ]
        for e in ordenados
    ]


def membrete(usuario: Usuario) -> pdf.Membrete:
    return pdf.Membrete(
        nombre=usuario.nombre_completo or usuario.nombre or "",
        rubro=RUBROS.get(usuario.rubro or "", ""),
        localidad=usuario.localidad or "",
        matricula=usuario.matricula,
    )


def armar_pdf(ctx: Contexto, f: FiltrosConsulta, eventos: list[Evento]) -> bytes:
    tabla = pdf.Tabla(("Fecha", "Campo", "Registro", "Detalle"), (18, 26, 28, 48), filas(eventos))
    generado = ctx.ahora.astimezone(config.zona_horaria)
    return pdf.documento(
        membrete(ctx.usuario), "Registro de trabajo", descripcion(f, eventos), resumen(eventos), tabla, generado
    )


COLUMNAS_PLANILLA = (
    "Fecha",
    "Campo",
    "Lote",
    "Lote destino",
    "Categoría",
    "Tipo",
    "Producto",
    "Dosis",
    "Cantidad",
    "Animales",
    "Caravana",
    "Valor",
    "Unidad",
    "Descripción",
)


def filas_planilla(eventos: list[Evento]) -> list[list[planilla.Valor]]:
    """Una columna por dato, con números y fechas como tales, para filtrar y sumar."""
    ordenados = sorted(eventos, key=lambda e: (e.fecha_evento, e.id))
    return [
        [
            e.fecha_evento,
            e.nombre_establecimiento,
            e.nombre_lote,
            e.nombre_lote_destino,
            e.categoria,
            formato.nombre_tipo(e.tipo),
            e.producto,
            e.dosis,
            e.cantidad_animales,
            e.categoria_animal,
            e.caravana,
            e.valor,
            e.unidad,
            e.descripcion,
        ]
        for e in ordenados
    ]


def armar_excel(ctx: Contexto, f: FiltrosConsulta, eventos: list[Evento]) -> bytes:
    return planilla.excel_bytes(
        membrete(ctx.usuario),
        "Registro de trabajo",
        descripcion(f, eventos),
        resumen(eventos),
        COLUMNAS_PLANILLA,
        filas_planilla(eventos),
        ctx.ahora.astimezone(config.zona_horaria),
    )


def manejar(ctx: Contexto, datos: Exportar) -> str:
    eventos = ctx.cuaderno.buscar(filtros(datos.consulta))
    if not eventos:
        return SIN_RESULTADOS
    nombre = f"{NOMBRE}-registros-{ctx.hoy.isoformat()}"
    que = datos.exportar.formato
    if que == "excel":
        ctx.adjuntos.append(Adjunto(f"{nombre}.xlsx", armar_excel(ctx, datos.consulta, eventos), XLSX))
        titulo = "📊 *PLANILLA LISTA*"
    elif que == "csv":
        contenido = planilla.csv_bytes(COLUMNAS_PLANILLA, filas_planilla(eventos))
        ctx.adjuntos.append(Adjunto(f"{nombre}.csv", contenido, CSV))
        titulo = "📊 *CSV LISTO*"
    else:
        propio = PDFS.get((datos.consulta.tipo or "").lower())
        del_tipo = propio[1](ctx, datos.consulta, eventos) if propio else None
        if propio and del_tipo is not None:
            nombre = f"{propio[0]}-{ctx.hoy.isoformat()}"
        ctx.adjuntos.append(Adjunto(f"{nombre}.pdf", del_tipo or armar_pdf(ctx, datos.consulta, eventos), PDF))
        titulo = "📄 *PDF LISTO*"
    return (
        f"{titulo}\n{' · '.join(descripcion(datos.consulta, eventos))}\n\n{LINEA}\n"
        "_Te lo mando acá abajo. Reenvialo a quien quieras._"
    )


ACCION = Accion("exportar", Exportar, manejar)
