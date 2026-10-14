"""Tipos para validar lo que devuelve la IA.

El modelo de lenguaje puede devolver cualquier cosa: textos donde van números, fechas
inventadas, campos de más. Cada acción declara su esquema con estos tipos, que limpian
el valor (recortan, convierten) o lo dejan en None si no sirve. Lo que no entra en el
esquema de su acción se descarta y el mensaje se trata como fuera de alcance.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict


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


def _a_fecha(valor: object) -> date | None:
    try:
        return date.fromisoformat(str(valor)) if valor is not None else None
    except ValueError:
        return None


def texto(largo: int, minuscula: bool = False) -> BeforeValidator:
    """Para usar en un campo:  tipo: Annotated[str | None, texto(30, minuscula=True)]"""

    def limpiar(valor: object) -> str | None:
        limpio = limpiar_texto(valor, largo)
        return limpio.lower() if limpio and minuscula else limpio

    return BeforeValidator(limpiar)


Entero = Annotated[int | None, BeforeValidator(_a_entero)]
Decimal = Annotated[float | None, BeforeValidator(_a_decimal)]
# Una fecha que no es YYYY-MM-DD ("ayer" sin convertir) queda en None.
Fecha = Annotated[date | None, BeforeValidator(_a_fecha)]
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


class EsquemaAccion(Esquema):
    """Una acción de la respuesta de la IA. Cada módulo la extiende con sus datos."""

    intencion: str
    # Establecimiento que NOMBRA el mensaje, tal como lo escribió la persona.
    establecimiento: Annotated[str | None, texto(120)] = None


Rubro = Annotated[
    Literal["granos", "hacienda"] | None,
    BeforeValidator(lambda v: v if v in ("granos", "hacienda") else None),
]
