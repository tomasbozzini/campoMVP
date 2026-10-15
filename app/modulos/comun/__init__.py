"""Módulo común, para todos los perfiles: cuaderno, consultas, precios y SENASA."""

from app.modulos.comun import borrar, consultar, conversacion, corregir, establecimiento, precios, registrar, senasa
from app.modulos.comun.glosario import GLOSARIO
from app.modulos.comun.prompt import PROMPT

ACCIONES = [
    registrar.ACCION,
    corregir.ACCION,
    borrar.ACCION,
    consultar.ACCION,
    establecimiento.ACCION,
    precios.ACCION,
    senasa.ACCION,
    *conversacion.ACCIONES,
]

__all__ = ["ACCIONES", "GLOSARIO", "PROMPT"]
