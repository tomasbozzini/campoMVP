"""Las cuentas del tacto (etapa 2, paso 3): preñadas, vacías, total de vientres, % de preñez y
CC promedio, del cierre de un lote o de las vacas dictadas una por una.

Reglas (docs/arquitectura.md, decisiones de producto de la etapa 2, "Cierre del tacto"):
- Se guarda como lo dijo. Si cabeza + cuerpo + cola no da las preñadas, las preñadas son las
  que dijo y se avisa la diferencia; si no dijo las preñadas, son la suma.
- El total es preñadas + vacías. Si dijo el total y falta uno de los dos, el que falta es la
  resta; si dijo los tres y no cierran, se avisa y el total es preñadas + vacías.
- El % sale de las preñadas sobre el total, redondeado a un decimal (88 de 102: 86,3 %).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

PRENADA, VACIA = "prenada", "vacia"
ESTADIOS = ("cabeza", "cuerpo", "cola")


def redondear(valor: float) -> float:
    """A un decimal, con la mitad para arriba (86,25 -> 86,3), no al par como `round`."""
    return float(Decimal(str(valor)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def porcentaje(parte: int, total: int) -> float | None:
    """88 de 102 -> 86,3. None si el total es 0."""
    return redondear(parte * 100 / total) if total > 0 else None


@dataclass(frozen=True)
class Diferencia:
    """Dos números que tendrían que dar lo mismo y no dan: "cabeza, cuerpo y cola suman 86;
    dijiste 88"."""

    que: str  # qué se sumó: "cabeza, cuerpo y cola", "preñadas y vacías"
    suman: int
    dijo: int


@dataclass(frozen=True)
class Cuentas:
    prenadas: int | None
    vacias: int | None
    total: int | None
    porcentaje: float | None
    estadios: dict[str, int] = field(default_factory=dict)  # cabeza, cuerpo, cola: los que hay
    cc: float | None = None  # la CC promedio
    con_cc: int = 0  # vaca por vaca: de cuántas vacas sale la CC promedio
    diferencias: tuple[Diferencia, ...] = ()


def _que(nombres: Sequence[str]) -> str:
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


def de_cierre(
    prenadas: int | None = None,
    cabeza: int | None = None,
    cuerpo: int | None = None,
    cola: int | None = None,
    vacias: int | None = None,
    total: int | None = None,
    cc: float | None = None,
) -> Cuentas:
    """Las cuentas del cierre de un lote, con los números como los dijo."""
    estadios = {n: v for n, v in zip(ESTADIOS, (cabeza, cuerpo, cola), strict=True) if v is not None}
    diferencias: list[Diferencia] = []
    if estadios:
        suma = sum(estadios.values())
        if prenadas is None:
            prenadas = suma
        elif suma != prenadas and (len(estadios) == len(ESTADIOS) or suma > prenadas):
            # Con las tres tienen que dar las preñadas; con menos, no pueden pasarse.
            diferencias.append(Diferencia(_que(list(estadios)), suma, prenadas))
    if total is not None:
        if prenadas is not None and vacias is not None:
            if prenadas + vacias != total:
                diferencias.append(Diferencia("preñadas y vacías", prenadas + vacias, total))
                total = prenadas + vacias
        elif prenadas is not None and total >= prenadas:
            vacias = total - prenadas
        elif vacias is not None and total >= vacias:
            prenadas = total - vacias
    elif prenadas is not None and vacias is not None:
        total = prenadas + vacias
    return Cuentas(
        prenadas=prenadas,
        vacias=vacias,
        total=total,
        # Más preñadas que el total ("40 preñadas de 30") no da un porcentaje.
        porcentaje=porcentaje(prenadas, total)
        if prenadas is not None and total is not None and prenadas <= total
        else None,
        estadios=estadios,
        cc=redondear(cc) if cc is not None else None,
        diferencias=tuple(diferencias),
    )


@dataclass(frozen=True)
class Vaca:
    """Una vaca dictada: "213 preñada cabeza CC 3"."""

    resultado: str  # PRENADA o VACIA
    estadio: str | None = None  # cabeza, cuerpo o cola
    cc: float | None = None


def de_vacas(vacas: Sequence[Vaca]) -> Cuentas:
    """Las cuentas de las vacas dictadas una por una."""
    prenadas = sum(v.resultado == PRENADA for v in vacas)
    estadios = {n: c for n in ESTADIOS if (c := sum(v.resultado == PRENADA and v.estadio == n for v in vacas))}
    ccs = [v.cc for v in vacas if v.cc is not None]
    return Cuentas(
        prenadas=prenadas,
        vacias=len(vacas) - prenadas,
        total=len(vacas),
        porcentaje=porcentaje(prenadas, len(vacas)),
        estadios=estadios,
        cc=redondear(sum(ccs) / len(ccs)) if ccs else None,
        con_cc=len(ccs),
    )


def comparar(cierre: Cuentas, vacas: Cuentas) -> list[tuple[str, int, int]]:
    """Lo que no coincide entre el cierre y las vacas dictadas: (qué, en las vacas, en el
    cierre). Solo lo que dicen los dos."""
    pares = [
        ("preñadas", vacas.prenadas, cierre.prenadas),
        *((n, vacas.estadios.get(n, 0), cierre.estadios[n]) for n in ESTADIOS if n in cierre.estadios),
        ("vacías", vacas.vacias, cierre.vacias),
        ("total", vacas.total, cierre.total),
    ]
    return [(que, a, b) for que, a, b in pares if a is not None and b is not None and a != b]
