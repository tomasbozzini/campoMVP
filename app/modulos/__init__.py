"""Módulos de funcionalidades. Cada uno declara sus acciones, lo que le suma al prompt y su
glosario para la transcripción; `cargar()` los registra.

Para sumar un módulo: crear su paquete `app/modulos/<nombre>/` con una lista ACCIONES, su
PROMPT (`ia.prompt.Parte`, que ofrece justo esas acciones) y su GLOSARIO (las palabras que
Whisper tiene que escribir bien), agregarlo a MODULOS y a los rubros que lo usan en
MODULOS_POR_RUBRO.
"""

import threading
from collections.abc import Sequence
from importlib import import_module

from app.ia.prompt import Parte
from app.nucleo import acciones
from app.nucleo.acciones import Accion

COMUN = "comun"
# Los módulos que existen, en el orden en que se arma el prompt.
MODULOS = [COMUN, "ganaderia"]

# Los módulos de cada rubro (`perfil.RUBROS`), además del común, que lo tienen todos. Los
# que todavía no existen (no están en MODULOS) no se ofrecen: agricultura llega en la etapa 3.
MODULOS_POR_RUBRO: dict[str, tuple[str, ...]] = {
    "veterinario": ("ganaderia",),
    "agronomo": ("agricultura",),
    "productor": ("ganaderia", "agricultura"),
}

# Whisper lee como mucho 224 tokens de glosario. En castellano son unos 3 caracteres por
# token: con 500 caracteres queda margen. Un test lo verifica para cada rubro.
LARGO_MAXIMO_GLOSARIO = 500

# Largo máximo del prompt de cada rubro, en caracteres (unos 4 por token, medido en el paso 1
# de la etapa 2). Casi todo el prompt sale del caché, pero Cerebras cobra igual el token del
# caché: el costo de cada mensaje crece con el largo. Si un rubro necesita pasar su tope, la
# precisión del set baja de 95 % o la p95 pasa de 3 s, se mira separar la IA en dos pasos.
# Un test lo verifica para cada rubro.
LARGO_MAXIMO_PROMPT: dict[str, int] = {
    "veterinario": 30_000,  # común + ganadería
    "agronomo": 34_000,  # común + agricultura
    "productor": 40_000,  # los tres
}

_candado = threading.Lock()
_cargados = False
_partes: dict[str, Parte] = {}
_glosarios: dict[str, tuple[str, ...]] = {}


def registrar(nombre: str, lista: Sequence[Accion], parte: Parte, glosario: Sequence[str] = ()) -> None:
    """Las acciones de un módulo, su parte del prompt (que tiene que ofrecer justo esas) y
    su glosario."""
    if sorted(parte.intenciones) != sorted(a.intencion for a in lista):
        raise ValueError(f"El prompt del módulo {nombre!r} no ofrece las mismas intenciones que sus acciones")
    acciones.registrar(nombre, *lista)
    _partes[nombre] = parte
    _glosarios[nombre] = tuple(glosario)


def cargar() -> None:
    """Registra todos los módulos. Se llama una vez al arrancar el servidor y los comandos
    de terminal; las llamadas siguientes no hacen nada."""
    global _cargados
    with _candado:
        if _cargados:
            return
        for nombre in MODULOS:
            modulo = import_module(f"app.modulos.{nombre}")
            registrar(nombre, modulo.ACCIONES, modulo.PROMPT, modulo.GLOSARIO)
        _cargados = True


def del_rubro(rubro: str | None) -> list[str]:
    """Los módulos que usa una persona según su rubro, en el orden de MODULOS."""
    suyos = {COMUN, *MODULOS_POR_RUBRO.get(rubro or "", ())}
    return [nombre for nombre in MODULOS if nombre in suyos]


def partes(nombres: Sequence[str]) -> list[Parte]:
    """Las partes del prompt de esos módulos, en ese orden."""
    return [_partes[nombre] for nombre in nombres]


def glosario(nombres: Sequence[str], propios: Sequence[str] = ()) -> str:
    """El glosario para Whisper con las palabras de esos módulos, en ese orden y sin
    repetir: "vaquillonas, novillos, ...". Después, los nombres propios de la persona (sus
    campos y lotes, "El Ombú") que entren en LARGO_MAXIMO_GLOSARIO. Vacío si no hay nada."""
    palabras = list(dict.fromkeys(p for nombre in nombres for p in _glosarios[nombre]))
    for propio in dict.fromkeys(propios):
        if propio in palabras:
            continue
        if len(", ".join([*palabras, propio]) + ".") > LARGO_MAXIMO_GLOSARIO:
            break
        palabras.append(propio)
    return ", ".join(palabras) + "." if palabras else ""
