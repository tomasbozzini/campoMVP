"""Registro de acciones: qué puede pedir la IA y qué hace el código con cada pedido.

Cada módulo registra sus acciones con:
- `esquema`: qué datos puede devolver la IA para esa acción (Pydantic). Lo que no valida
  se descarta y se responde como fuera de alcance.
- `manejar`: qué hace el código y qué responde. El texto lo arma siempre el código.
- `juntar` (opcional): para acciones que, si vienen varias en un mismo mensaje, se
  responden juntas (por ejemplo, los precios: una sola respuesta agrupada por fuente).

El núcleo no conoce las acciones: las busca en el registro por su `intencion`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.ia.esquemas import EsquemaAccion
from app.nucleo.contexto import Contexto


@dataclass(frozen=True)
class Accion:
    intencion: str
    esquema: type[EsquemaAccion]
    manejar: Callable[[Contexto, Any], str]
    # Se responden juntas las acciones de este tipo para las que `se_junta` da True.
    juntar: Callable[[Contexto, list[Any]], str] | None = None
    se_junta: Callable[[Any], bool] = lambda _datos: True
    # Si el mensaje trae otros pedidos, esta acción no se responde ("hola, ¿cuánto está la soja?").
    se_omite_si_hay_otras: bool = False


_registro: dict[str, Accion] = {}


def registrar(*acciones: Accion) -> None:
    for accion in acciones:
        if accion.intencion in _registro:
            raise ValueError(f"La acción {accion.intencion!r} ya está registrada")
        _registro[accion.intencion] = accion


def buscar(intencion: object) -> Accion | None:
    return _registro.get(intencion) if isinstance(intencion, str) else None


def validar(accion: Accion, datos: dict) -> EsquemaAccion | None:
    """Los datos de la IA validados con el esquema de la acción; None si no validan."""
    try:
        return accion.esquema.model_validate(datos)
    except ValidationError:
        return None


def intenciones() -> list[str]:
    return list(_registro)
