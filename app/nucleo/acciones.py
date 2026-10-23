"""Registro de acciones: qué puede pedir la IA y qué hace el código con cada pedido.

Cada módulo registra sus acciones con:
- `esquema`: qué datos puede devolver la IA para esa acción (Pydantic). Lo que no valida
  se descarta y se responde como fuera de alcance.
- `manejar`: qué hace el código y qué responde. El texto lo arma siempre el código.
- `juntar` (opcional): para acciones que, si vienen varias en un mismo mensaje, se
  responden juntas (por ejemplo, los precios: una sola respuesta agrupada por fuente).

El núcleo no conoce las acciones: las busca en el registro por su `intencion`. Cada acción
queda registrada con su módulo, y solo se ejecuta para quien tiene ese módulo.
"""

import logging
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from pydantic import BaseModel, ValidationError

from app.ia.esquemas import EsquemaAccion, intencion_valida
from app.ia.fechas import FechaDudosa
from app.nucleo.contexto import Contexto

log = logging.getLogger(__name__)


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
    # El módulo de la acción: lo completa `registrar`.
    modulo: str = ""


_registro: dict[str, Accion] = {}


def registrar(modulo: str, *acciones: Accion) -> None:
    for accion in acciones:
        if accion.intencion in _registro:
            raise ValueError(f"La acción {accion.intencion!r} ya está registrada")
        _registro[accion.intencion] = replace(accion, modulo=modulo)


def buscar(intencion: object, modulos: Collection[str] | None = None) -> Accion | None:
    """La acción de la intención que devolvió la IA, si es de esos módulos (de todos si no se
    dicen). Un nombre casi igual a uno de ellos ("borrar_pendente") se toma como ese
    (`esquemas.intencion_valida`); el de una intención de otro módulo, no."""
    if isinstance(intencion, str) and intencion in _registro:
        accion = _registro[intencion]
        return accion if modulos is None or accion.modulo in modulos else None
    validas = [i for i, a in _registro.items() if modulos is None or a.modulo in modulos]
    nombre = intencion_valida(intencion, validas)
    if nombre is None:
        return None
    if nombre != intencion:
        # Sin el nombre que vino: lo escribe la IA y podría traer algo del mensaje.
        log.info("Intención casi igual tomada como %s", nombre)
    return _registro[nombre]


def validar(
    accion: Accion, datos: dict[str, Any], hoy: date, fechas: dict[str, str] | None = None
) -> EsquemaAccion | None:
    """Los datos de la IA validados con el esquema de la acción; None si no validan. Las
    fechas se calculan con `hoy` y con las que la persona eligió (`fechas`); si una es dudosa,
    se levanta `FechaDudosa`."""
    try:
        return accion.esquema.model_validate(datos, context={"hoy": hoy, "fechas": fechas or {}})
    except ValidationError:
        return None


def intenciones() -> list[str]:
    return list(_registro)


def _fechas_de(valor: object) -> list[date]:
    if isinstance(valor, BaseModel):
        return [f for campo in type(valor).model_fields for f in _fechas_de(getattr(valor, campo))]
    if isinstance(valor, list):
        return [f for v in valor for f in _fechas_de(v)]
    return [valor] if isinstance(valor, date) else []


def fechas(interpretado: object, hoy: date) -> tuple[str, ...]:
    """Las fechas que quedan de la respuesta de la IA, en orden, como las calcula el bot, y
    "dudosa" si el bot pregunta cuál es (para el set de evaluación)."""
    crudas = interpretado.get("acciones") if isinstance(interpretado, dict) else None
    lista = crudas if isinstance(crudas, list) else [interpretado]
    encontradas: list[str] = []
    for pedido in lista:
        if not isinstance(pedido, dict) or (accion := buscar(pedido.get("intencion"))) is None:
            continue
        try:
            datos = validar(accion, pedido, hoy)
        except FechaDudosa:
            encontradas.append("dudosa")  # el bot pregunta
            continue
        encontradas += [f.isoformat() for f in _fechas_de(datos)]
    return tuple(encontradas)
