"""Las fechas las calcula el código, no la IA (paso 8.5.1 del plan).

El modelo calculaba mal los días de la semana y si eran pasados o futuros ("tenía que
pagarle al contratista el sábado" daba el viernes que viene). Ahora devuelve lo que dijo la
persona en un formato fijo (FECHA) y acá se convierte con la fecha de hoy en hora argentina:

- {"dias": -1}: días para atrás o para adelante ("ayer", "anteayer", "en 21 días").
- {"dia_semana": "sabado", "cual": "pasado"}: el más reciente antes de hoy, o el primero
  después de hoy con "proximo". "El sábado" dicho un sábado es hace 7 días o dentro de 7.
- {"dia": 22, "mes": 10}: con el mes, el 22/10 más cercano a hoy (de este año, el anterior o
  el siguiente); sin el mes, el 22 de este mes, el anterior o el siguiente, el más cercano a
  hoy en el sentido que corresponde. Si también dice el día de la semana y no coincide ("el
  viernes 22" cuando el 22 es jueves), se levanta `FechaDudosa` para preguntarle.

Sin "cual", el sentido lo pone el dato: los registros y las consultas miran para atrás y los
pendientes para adelante. Los períodos de las consultas ("esta semana", "el mes pasado")
también los arma el código, con la semana de lunes a domingo.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from app.infra.texto import sin_tildes

DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
PASADO, PROXIMO = "pasado", "proximo"
PERIODOS = ("hoy", "ayer", "esta_semana", "semana_pasada", "este_mes", "mes_pasado", "este_anio", "anio_pasado")
MAX_DIAS = 400  # "en 21 días", "hace 3 días": más que esto no es una fecha dicha


class FechaDudosa(Exception):
    """El día de la semana y el número no coinciden ("el viernes 22" cuando el 22 es jueves).
    `opciones`: la fecha por el número y la del día de la semana más cercano a ella."""

    def __init__(self, clave: str, opciones: tuple[date, date]) -> None:
        super().__init__(clave)
        self.clave = clave
        self.opciones = opciones


@dataclass(frozen=True)
class Dicha:
    """Una fecha tal como la dijo la persona. `dia_semana`: 0 es lunes."""

    dias: int | None = None
    dia_semana: int | None = None
    cual: str | None = None
    dia: int | None = None
    mes: int | None = None
    anio: int | None = None

    @property
    def clave(self) -> str:
        """Para recordar qué fecha eligió la persona cuando se le preguntó: "4|22|None|None"."""
        return f"{self.dia_semana}|{self.dia}|{self.mes}|{self.anio}"


def entero(valor: object, minimo: int, maximo: int) -> int | None:
    if isinstance(valor, bool) or not isinstance(valor, int | float | str):
        return None
    try:
        numero = int(float(valor))
    except ValueError:
        return None
    return numero if minimo <= numero <= maximo else None


def _palabra(valor: object) -> str:
    return sin_tildes(str(valor).strip().lower()) if isinstance(valor, str) else ""


def leer(valor: object) -> Dicha | None:
    """La FECHA que devolvió la IA, limpia; None si no dice una fecha (un texto como "ayer" o
    "2026-10-20" tampoco: la IA no calcula fechas)."""
    if not isinstance(valor, dict):
        return None
    nombre = _palabra(valor.get("dia_semana"))
    cual = _palabra(valor.get("cual"))
    dicha = Dicha(
        dias=entero(valor.get("dias"), -MAX_DIAS, MAX_DIAS),
        dia_semana=DIAS.index(nombre) if nombre in DIAS else None,
        cual=cual if cual in (PASADO, PROXIMO) else None,
        dia=entero(valor.get("dia"), 1, 31),
        mes=entero(valor.get("mes"), 1, 12),
        anio=entero(valor.get("anio"), 2000, 2100),
    )
    return dicha if (dicha.dias, dicha.dia_semana, dicha.dia) != (None, None, None) else None


def _fecha(anio: int, mes: int, dia: int) -> date | None:
    try:
        return date(anio, mes, dia)
    except ValueError:  # el 31 de noviembre
        return None


def _mes(hoy: date, corrimiento: int) -> tuple[int, int]:
    """(año, mes) de este mes corrido `corrimiento` meses."""
    total = hoy.year * 12 + hoy.month - 1 + corrimiento
    return total // 12, total % 12 + 1


def dia_de_semana(hoy: date, dia_semana: int, sentido: str) -> date:
    """El más reciente antes de hoy o el primero después de hoy: nunca hoy."""
    if sentido == PASADO:
        return hoy - timedelta(days=(hoy.weekday() - dia_semana) % 7 or 7)
    return hoy + timedelta(days=(dia_semana - hoy.weekday()) % 7 or 7)


def _por_numero(d: Dicha, hoy: date, sentido: str) -> date | None:
    assert d.dia is not None
    if d.mes is not None:
        anios = [d.anio] if d.anio else [hoy.year - 1, hoy.year, hoy.year + 1]
        candidatas = [f for a in anios if (f := _fecha(a, d.mes, d.dia))]
    else:
        meses = [_mes(hoy, c) for c in (-1, 0, 1)]
        candidatas = [f for a, m in meses if (f := _fecha(a, m, d.dia))]
        candidatas = [f for f in candidatas if (f <= hoy if sentido == PASADO else f >= hoy)]
    return min(candidatas, key=lambda f: abs((f - hoy).days), default=None)


def _mas_cercano(fecha: date, dia_semana: int) -> date:
    """El día de esa semana más cercano a la fecha (hasta 3 días antes o después)."""
    corrimiento = (dia_semana - fecha.weekday()) % 7
    return fecha + timedelta(days=corrimiento - 7 if corrimiento > 3 else corrimiento)


def calcular(d: Dicha, hoy: date, sentido: str, elegidas: Mapping[str, str] | None = None) -> date | None:
    """La fecha de lo que dijo la persona. `sentido`: hacia dónde mirar si no dijo "pasado"
    ni "próximo". `elegidas`: lo que ya respondió a una `FechaDudosa` (clave -> YYYY-MM-DD)."""
    if d.dias is not None:
        return hoy + timedelta(days=d.dias)
    sentido = d.cual or sentido
    if d.dia is None:
        return dia_de_semana(hoy, d.dia_semana, sentido) if d.dia_semana is not None else None
    fecha = _por_numero(d, hoy, sentido)
    if fecha is None or d.dia_semana is None or fecha.weekday() == d.dia_semana:
        return fecha
    if elegida := (elegidas or {}).get(d.clave):
        return date.fromisoformat(elegida)
    raise FechaDudosa(d.clave, (fecha, _mas_cercano(fecha, d.dia_semana)))


def periodo(nombre: str, hoy: date) -> tuple[date, date] | None:
    """(desde, hasta) de un período con nombre. "Este mes" y "esta semana" llegan hasta hoy."""
    lunes = hoy - timedelta(days=hoy.weekday())
    primero = hoy.replace(day=1)
    rangos = {
        "hoy": (hoy, hoy),
        "ayer": (hoy - timedelta(days=1), hoy - timedelta(days=1)),
        "esta_semana": (lunes, hoy),
        "semana_pasada": (lunes - timedelta(days=7), lunes - timedelta(days=1)),
        "este_mes": (primero, hoy),
        "mes_pasado": ((primero - timedelta(days=1)).replace(day=1), primero - timedelta(days=1)),
        "este_anio": (date(hoy.year, 1, 1), hoy),
        "anio_pasado": (date(hoy.year - 1, 1, 1), date(hoy.year - 1, 12, 31)),
    }
    return rangos.get(nombre)


def mes_entero(mes: int, hoy: date) -> tuple[date, date]:
    """Un mes por su número ("en septiembre"): el más reciente, este año si ya empezó."""
    anio = hoy.year if mes <= hoy.month else hoy.year - 1
    siguiente = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
    return date(anio, mes, 1), siguiente - timedelta(days=1)
