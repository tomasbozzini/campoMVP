"""Exportar: los registros que pide la persona en un archivo, que le llega por WhatsApp.

"mandame un PDF de lo que hice en La Pastora este mes": la IA arma los mismos filtros que
en una consulta y el formato; el código busca, suma y arma el archivo. El PDF lleva el
membrete del profesional (nombre, rubro, localidad y matrícula) y el pie legal (decisión
de producto "Salidas"). En esta etapa le llega solo al profesional, que lo reenvía.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field

from app.ia.esquemas import Esquema, EsquemaAccion, SiNoVacio
from app.infra.config import config
from app.infra.modelos import Evento, Usuario
from app.modulos.comun.consultar import FiltrosConsulta, filtros
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Adjunto, Contexto
from app.nucleo.perfil import RUBROS
from app.salidas import pdf
from app.salidas import whatsapp as formato
from app.salidas.whatsapp import SEPARADOR as LINEA

PDF = "application/pdf"
SIN_RESULTADOS = "🔍 No encontré registros para armar el archivo.\nProbá con otro período, lote o campo."

Formato = Literal["pdf", "excel", "csv"]


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


def manejar(ctx: Contexto, datos: Exportar) -> str:
    eventos = ctx.cuaderno.buscar(filtros(datos.consulta))
    if not eventos:
        return SIN_RESULTADOS
    if datos.exportar.formato != "pdf":
        return "📄 Por ahora te puedo mandar tus registros en *PDF*: pedímelo así, por ejemplo _mandame un PDF de este mes_."
    nombre = f"CampoBot-registros-{ctx.hoy.isoformat()}.pdf"
    ctx.adjuntos.append(Adjunto(nombre, armar_pdf(ctx, datos.consulta, eventos), PDF))
    return (
        f"📄 *PDF LISTO*\n{' · '.join(descripcion(datos.consulta, eventos))}\n\n{LINEA}\n"
        "_Te lo mando acá abajo. Reenvialo a quien quieras._"
    )


ACCION = Accion("exportar", Exportar, manejar)
