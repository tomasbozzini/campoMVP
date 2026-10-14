"""Módulos de funcionalidades. Cada uno declara sus acciones; `cargar()` las registra.

Para sumar un módulo: crear su paquete con una lista ACCIONES y agregarlo a MODULOS.
"""

import threading
from importlib import import_module

from app.nucleo import acciones

MODULOS = ["app.modulos.comun"]

_candado = threading.Lock()
_cargados = False


def cargar() -> None:
    """Registra las acciones de todos los módulos. Se llama una vez al arrancar el servidor
    y los comandos de terminal; las llamadas siguientes no hacen nada."""
    global _cargados
    with _candado:
        if _cargados:
            return
        for nombre in MODULOS:
            acciones.registrar(*import_module(nombre).ACCIONES)
        _cargados = True
