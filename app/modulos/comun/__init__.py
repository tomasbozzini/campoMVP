"""Módulo común, para todos los perfiles: cuaderno, consultas, sesiones, pendientes, precios,
SENASA y lo de la cuenta (ayuda, privacidad, mis campos, mis datos)."""

from app.modulos.comun import (
    borrar,
    consultar,
    conversacion,
    corregir,
    cuenta,
    establecimiento,
    exportar,
    pendientes,
    precios,
    registrar,
    renombrar,
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
    exportar.ACCION,
    establecimiento.ACCION,
    *renombrar.ACCIONES,
    precios.ACCION,
    senasa.ACCION,
    *sesion.ACCIONES,
    *pendientes.ACCIONES,
    *cuenta.ACCIONES,
    *conversacion.ACCIONES,
]

__all__ = ["ACCIONES", "GLOSARIO", "PROMPT"]
