"""Módulos de funcionalidades. Cada uno declara sus acciones; `cargar()` las registra.

Para sumar un módulo: crear su paquete con una lista ACCIONES y agregarlo a MODULOS.
"""

from app.nucleo import acciones

MODULOS = ["app.modulos.comun"]

_cargados = False


def cargar() -> None:
    global _cargados
    if _cargados:
        return
    from importlib import import_module

    for nombre in MODULOS:
        acciones.registrar(*import_module(nombre).ACCIONES)
    _cargados = True
