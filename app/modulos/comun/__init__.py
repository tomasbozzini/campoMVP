"""Módulo común, para todos los perfiles: cuaderno, consultas, sesiones, pendientes, precios y SENASA."""

from app.modulos.comun import (
    borrar,
    consultar,
    conversacion,
    corregir,
    establecimiento,
    pendientes,
    precios,
    registrar,
    senasa,
    sesion,
)
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
    *sesion.ACCIONES,
    *pendientes.ACCIONES,
    *conversacion.ACCIONES,
]

__all__ = ["ACCIONES", "GLOSARIO", "PROMPT"]
