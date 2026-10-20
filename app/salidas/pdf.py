"""PDF con la marca del producto (`infra/marca.py`): el membrete del profesional, lo que pidió y el pie legal.

Se arma con fpdf2 y la fuente estándar Helvetica. El texto que escribió la persona va
siempre como texto: nunca se interpreta (sin markdown ni HTML). Lo que la fuente no tiene
(emojis, flechas) se reemplaza o se saca. El logo está pendiente de definición (plan,
"Pendientes de definición"): por ahora la marca es el nombre.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fpdf.fonts import FontFace

from app.infra.marca import NOMBRE

# Decisión de producto "Salidas" (docs/arquitectura.md), textual.
PIE = (
    f"Registro de lo informado por el profesional. {NOMBRE} es un auxiliar de cálculo y registro: "
    "no realiza recomendaciones ni reemplaza la prescripción profesional."
)
VERDE = (46, 125, 50)
GRIS = (100, 100, 100)
ANCHO = 180  # A4 (210 mm) menos los márgenes

_REEMPLAZOS = str.maketrans(
    {"→": "->", "–": "-", "—": "-", "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...", "•": "·"}
)


def latin1(texto: str) -> str:
    """Lo que entra en Helvetica: las flechas y comillas tipográficas se cambian por su
    equivalente y lo demás que no está en Latin-1 (emojis) se saca."""
    limpio = texto.translate(_REEMPLAZOS).encode("latin-1", "ignore").decode("latin-1")
    return " ".join(limpio.split())


@dataclass(frozen=True)
class Membrete:
    """Quién firma el documento: va arriba de todo."""

    nombre: str
    rubro: str
    localidad: str
    matricula: str | None = None

    def linea(self) -> str:
        partes = [self.nombre, self.rubro, self.localidad]
        if self.matricula:
            partes.append(f"Matrícula {self.matricula}")
        return " · ".join(p for p in partes if p)


@dataclass(frozen=True)
class Tabla:
    columnas: tuple[str, ...]
    anchos: tuple[int, ...]  # proporcionales
    filas: Sequence[Sequence[str]]


class _Documento(FPDF):  # type: ignore[misc]  # fpdf2 no trae tipos
    def __init__(self, generado: str) -> None:
        super().__init__(format="A4")
        self.generado = generado
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(auto=True, margin=22)
        self.set_author(NOMBRE)
        self.set_creator(NOMBRE)

    def header(self) -> None:
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*VERDE)
        self.cell(ANCHO / 2, 8, NOMBRE, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(*GRIS)
        self.cell(ANCHO / 2, 8, f"Generado el {self.generado}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*VERDE)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y() + 1, self.l_margin + ANCHO, self.get_y() + 1)
        self.ln(5)
        self.set_text_color(0, 0, 0)

    def footer(self) -> None:
        self.set_y(-17)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*GRIS)
        self.multi_cell(150, 3.4, latin1(PIE), new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font("Helvetica", "", 7.5)
        self.cell(ANCHO - 150, 3.4, f"Página {self.page_no()} de {{nb}}", align="R")


def documento(
    membrete: Membrete,
    titulo: str,
    subtitulo: list[str],
    resumen: list[str],
    tabla: Tabla,
    generado: datetime,
) -> bytes:
    """El PDF: título, membrete, de qué se trata (`subtitulo`), un resumen (los totales) y la
    tabla. `generado`: la hora local en que se pidió."""
    pdf = _Documento(generado.strftime("%d/%m/%Y %H:%M"))
    pdf.set_title(latin1(titulo))
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 7, latin1(titulo), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, latin1(membrete.linea()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if subtitulo:
        pdf.set_text_color(*GRIS)
        pdf.multi_cell(0, 5, latin1(" · ".join(subtitulo)), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)

    if resumen:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, "Totales", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 10)
        for linea in resumen:
            pdf.cell(0, 5, latin1(f"·  {linea}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(4)
    pdf.set_font("Helvetica", "", 9)
    encabezado = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=VERDE)
    with pdf.table(
        col_widths=tabla.anchos,
        width=ANCHO,
        headings_style=encabezado,
        line_height=4.6,
        text_align="LEFT",
        borders_layout="HORIZONTAL_LINES",
        cell_fill_color=(242, 247, 242),
        cell_fill_mode="ROWS",
    ) as t:
        fila = t.row()
        for columna in tabla.columnas:
            fila.cell(columna)
        for datos in tabla.filas:
            fila = t.row()
            for valor in datos:
                fila.cell(latin1(valor))
    return bytes(pdf.output())
