"""Módulo común, para todos los perfiles: cuaderno, consultas, precios y SENASA."""

from app.modulos.comun import borrar, consultar, conversacion, corregir, establecimiento, precios, registrar, senasa

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
