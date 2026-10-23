"""Tipos para validar lo que devuelve la IA.

El modelo de lenguaje puede devolver cualquier cosa: textos donde van números, fechas
inventadas, campos de más. Cada acción declara su esquema con estos tipos, que limpian
el valor (recortan, convierten) o lo dejan en None si no sirve. Lo que no entra en el
esquema de su acción se descarta y el mensaje se trata como fuera de alcance.
"""

import re
from collections.abc import Iterable
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Annotated, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationInfo, model_validator

from app.ia import fechas
from app.infra.config import config
from app.infra.texto import sin_tildes

# Desde qué parecido un nombre de intención que no existe se toma como uno que sí (paso 2 de
# la etapa 2): "borrar_pendente" y "borrar_pendiente" dan 0,97; "precios" y "precio", 0,92;
# "consulta" y "consultar", 0,94. "registro" y "registrar" (0,82) o "borrar_datos" y
# "borrar_mis_datos" (0,86) no alcanzan.
PARECIDO_INTENCION = 0.9


def intencion_valida(nombre: object, validas: Iterable[str]) -> str | None:
    """La intención de `validas` que nombró la IA: la misma, escrita con mayúsculas, espacios o
    guiones ("Borrar pendiente"), o casi igual a una sola de ellas ("borrar_pendente"). None si
    no es ninguna o si se parece a más de una."""
    if not isinstance(nombre, str):
        return None
    opciones = list(validas)
    limpio = re.sub(r"[\s-]+", "_", sin_tildes(nombre).strip().lower())
    if limpio in opciones:
        return limpio
    parecidas = [v for v in opciones if SequenceMatcher(None, limpio, v).ratio() >= PARECIDO_INTENCION]
    return parecidas[0] if len(parecidas) == 1 else None


def limpiar_texto(valor: object, largo: int) -> str | None:
    """Texto sin espacios de más y recortado; None si viene vacío.

    Un número sirve ("lote": 3 es el lote "3"), pero true/false, listas, objetos y el 0
    son la IA rellenando un campo que no tiene: quedan en None, no en "False" ni "[]".
    """
    if isinstance(valor, bool | list | dict) or (isinstance(valor, int | float) and valor == 0):
        return None
    if valor is None or str(valor).strip() == "":
        return None
    return str(valor).strip()[:largo]


def _a_entero(valor: object) -> int | None:
    try:
        return int(float(valor)) if valor is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


def _a_decimal(valor: object) -> float | None:
    try:
        return float(valor) if valor is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def hoy_de(info: ValidationInfo) -> date:
    """La fecha de hoy con la que se calculan las fechas: la que pasa el núcleo al validar
    (`acciones.validar`) o, si no, la de hoy en hora argentina."""
    contexto = info.context if isinstance(info.context, dict) else {}
    hoy = contexto.get("hoy")
    return hoy if isinstance(hoy, date) else datetime.now(config.zona_horaria).date()


def _a_fecha(sentido: str) -> BeforeValidator:
    """Una FECHA como la dijo la persona, calculada por el código (`ia/fechas.py`)."""

    def convertir(valor: object, info: ValidationInfo) -> date | None:
        dicha = fechas.leer(valor)
        if dicha is None:
            return None
        elegidas = info.context.get("fechas") if isinstance(info.context, dict) else None
        return fechas.calcular(dicha, hoy_de(info), sentido, elegidas)

    return BeforeValidator(convertir)


def texto(largo: int, minuscula: bool = False) -> BeforeValidator:
    """Para usar en un campo:  tipo: Annotated[str | None, texto(30, minuscula=True)]"""

    def limpiar(valor: object) -> str | None:
        limpio = limpiar_texto(valor, largo)
        return limpio.lower() if limpio and minuscula else limpio

    return BeforeValidator(limpiar)


Entero = Annotated[int | None, BeforeValidator(_a_entero)]
Decimal = Annotated[float | None, BeforeValidator(_a_decimal)]
# La IA devuelve la fecha como la dijo la persona (FECHA, ver `ia/fechas.py`) y el código la
# calcula. Un texto ("ayer", "2026-10-20") no es una FECHA y queda en None. Sin decir "pasado"
# ni "próximo", `Fecha` mira para atrás (registros, consultas) y `FechaProxima` para adelante
# (pendientes). Si la fecha es dudosa, se levanta `fechas.FechaDudosa`.
Fecha = Annotated[date | None, _a_fecha(fechas.PASADO)]
FechaProxima = Annotated[date | None, _a_fecha(fechas.PROXIMO)]
# Solo True si la IA dijo exactamente true: "sí", 1 o "true" no alcanzan.
Bandera = Annotated[bool, BeforeValidator(lambda v: v is True)]


def _diccionario_o_vacio(valor: object) -> object:
    return valor if isinstance(valor, dict) else {}


def _diccionario_o_nada(valor: object) -> object:
    return valor if isinstance(valor, dict) else None


def _solo_diccionarios(valor: object) -> object:
    """Una lista de objetos: los elementos que no son objetos se descartan."""
    return [v for v in valor if isinstance(v, dict)] if isinstance(valor, list) else valor


# Un objeto anidado opcional: si no es un objeto, queda vacío / en None.
SiNoVacio = BeforeValidator(_diccionario_o_vacio)
SiNoNada = BeforeValidator(_diccionario_o_nada)
# Una lista de objetos (si no es una lista, la acción no valida).
SoloObjetos = BeforeValidator(_solo_diccionarios)


class Esquema(BaseModel):
    """Base de todo lo que devuelve la IA: los campos que no están declarados se ignoran."""

    model_config = ConfigDict(extra="ignore")


Periodo = Annotated[str | None, BeforeValidator(lambda v: v if v in fechas.PERIODOS else None)]
Mes = Annotated[int | None, BeforeValidator(lambda v: fechas.entero(v, 1, 12))]


class ConPeriodo(Esquema):
    """Filtros por fecha de una consulta: un período con nombre ("la semana pasada"), un mes
    ("en septiembre") o desde / hasta como FECHA. El código arma el rango: `desde` y `hasta`
    quedan calculados (lo que dice desde / hasta gana sobre el período)."""

    periodo: Periodo = None
    mes: Mes = None
    desde: Fecha = None
    hasta: Fecha = None

    @model_validator(mode="after")
    def _rango(self, info: ValidationInfo) -> Self:
        hoy = hoy_de(info)
        rango = fechas.periodo(self.periodo, hoy) if self.periodo else None
        if rango is None and self.mes:
            rango = fechas.mes_entero(self.mes, hoy)
        if rango:
            self.desde = self.desde or rango[0]
            self.hasta = self.hasta or rango[1]
        return self


class EsquemaAccion(Esquema):
    """Una acción de la respuesta de la IA. Cada módulo la extiende con sus datos."""

    intencion: str
    # Establecimiento que NOMBRA el mensaje, tal como lo escribió la persona.
    establecimiento: Annotated[str | None, texto(120)] = None


Rubro = Annotated[
    Literal["granos", "hacienda"] | None,
    BeforeValidator(lambda v: v if v in ("granos", "hacienda") else None),
]
