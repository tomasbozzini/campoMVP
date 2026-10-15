"""Módulos de funcionalidades. Cada uno declara sus acciones y lo que le suma al prompt;
`cargar()` los registra.

Para sumar un módulo: crear su paquete `app/modulos/<nombre>/` con una lista ACCIONES y su
PROMPT (`ia.prompt.Parte`, que ofrece justo esas acciones), agregarlo a MODULOS y a los
rubros que lo usan en MODULOS_POR_RUBRO.
"""

import threading
from collections.abc import Sequence
from importlib import import_module

from app.ia.prompt import Parte
from app.nucleo import acciones
from app.nucleo.acciones import Accion

COMUN = "comun"
# Los módulos que existen, en el orden en que se arma el prompt.
MODULOS = [COMUN]

# Los módulos de cada rubro (`perfil.RUBROS`), además del común, que lo tienen todos. Los
# que todavía no existen (no están en MODULOS) no se ofrecen: ganadería llega en la etapa 2
# y agricultura en la 3.
MODULOS_POR_RUBRO: dict[str, tuple[str, ...]] = {
    "veterinario": ("ganaderia",),
    "agronomo": ("agricultura",),
    "productor": ("ganaderia", "agricultura"),
}

_candado = threading.Lock()
_cargados = False
_partes: dict[str, Parte] = {}


def registrar(nombre: str, lista: Sequence[Accion], parte: Parte) -> None:
    """Las acciones de un módulo y su parte del prompt, que tiene que ofrecer justo esas."""
    if sorted(parte.intenciones) != sorted(a.intencion for a in lista):
        raise ValueError(f"El prompt del módulo {nombre!r} no ofrece las mismas intenciones que sus acciones")
    acciones.registrar(nombre, *lista)
    _partes[nombre] = parte


def cargar() -> None:
    """Registra todos los módulos. Se llama una vez al arrancar el servidor y los comandos
    de terminal; las llamadas siguientes no hacen nada."""
    global _cargados
    with _candado:
        if _cargados:
            return
        for nombre in MODULOS:
            modulo = import_module(f"app.modulos.{nombre}")
            registrar(nombre, modulo.ACCIONES, modulo.PROMPT)
        _cargados = True


def del_rubro(rubro: str | None) -> list[str]:
    """Los módulos que usa una persona según su rubro, en el orden de MODULOS."""
    suyos = {COMUN, *MODULOS_POR_RUBRO.get(rubro or "", ())}
    return [nombre for nombre in MODULOS if nombre in suyos]


def partes(nombres: Sequence[str]) -> list[Parte]:
    """Las partes del prompt de esos módulos, en ese orden."""
    return [_partes[nombre] for nombre in nombres]
