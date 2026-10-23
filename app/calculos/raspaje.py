"""Las cuentas del raspaje (etapa 2, paso 4): el número de muestreo de cada toro y la fecha para
repetir.

Reglas (docs/arquitectura.md, etapa 2, paso 4):
- Muestreo: si el raspaje anterior del mismo toro fue hace `SERIE_DIAS` días o menos, es el
  siguiente de esa serie; si no hay o fue antes, es el 1.° (el año siguiente arranca de nuevo).
- Repetir: solo con el intervalo que dice el profesional, como lo dijo ("15 días", "2
  semanas", "un mes"); la fecha la calcula el código.
"""

import calendar
import re
from collections.abc import Sequence
from datetime import date, timedelta

from app.infra.texto import sin_tildes

# Decisión de producto aprobada en el paso 4 (no es un umbral publicado): las repeticiones de
# un raspaje caen a las pocas semanas; el raspaje del año siguiente es otra serie.
SERIE_DIAS = 60
MAX_DIAS_REPETIR = 365

_NUMEROS = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "veinte": 20,
    "veintiun": 21, "veintiuno": 21, "treinta": 30,
}  # fmt: skip
_INTERVALO = re.compile(r"(\d+|[a-z]+)\s*(dia|semana|mes)")


def muestreo(anteriores: Sequence[tuple[date, int]], fecha: date) -> int:
    """El número de este raspaje. `anteriores`: (fecha, muestreo) de los raspajes de ese toro.
    Sigue la serie del último que no es posterior a `fecha`, si fue hace 60 días o menos."""
    previos = [a for a in anteriores if a[0] <= fecha]
    if not previos:
        return 1
    ultima, numero = max(previos)
    return numero + 1 if (fecha - ultima).days <= SERIE_DIAS else 1


def _sumar_meses(desde: date, meses: int) -> date:
    """El mismo día, `meses` después; si ese mes no lo tiene (31), el último del mes."""
    total = desde.month - 1 + meses
    anio, mes = desde.year + total // 12, total % 12 + 1
    return desde.replace(year=anio, month=mes, day=min(desde.day, calendar.monthrange(anio, mes)[1]))


def fecha_para_repetir(desde: date, intervalo: str | None) -> date | None:
    """ "15 días" desde el 13/10 -> 28/10; "2 semanas" -> 14 días; "un mes" -> el mismo día del
    mes siguiente. Un número solo son días. None si no se entiende o pasa del año."""
    if not intervalo:
        return None
    limpio = sin_tildes(intervalo).lower()
    if (encontrado := _INTERVALO.search(limpio)) is not None:
        cuantos_texto, unidad = encontrado.groups()
    elif (solo := re.fullmatch(r"\s*(\d+)\s*", limpio)) is not None:
        cuantos_texto, unidad = solo.group(1), "dia"
    else:
        return None
    cuantos = int(cuantos_texto) if cuantos_texto.isdecimal() else _NUMEROS.get(cuantos_texto)
    if not cuantos:
        return None
    if unidad == "mes":
        fecha = _sumar_meses(desde, cuantos)
    else:
        fecha = desde + timedelta(days=cuantos * (7 if unidad == "semana" else 1))
    return fecha if 0 < (fecha - desde).days <= MAX_DIAS_REPETIR else None
