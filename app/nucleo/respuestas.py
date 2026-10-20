"""Respuestas cortas a una pregunta del bot (*sí* / *no*), sin IA.

Además de "sí" y "no", se aceptan las variantes de siempre: "dale", "ok", "sí, borrá",
"de una", "no, dejá", "mejor no", "cancelá", "no, no, dejá, no quiero cambiar nada". Todas
las palabras tienen que ser de una respuesta del mismo lado: si mezcla un sí y un no ("dale,
no") o trae otra cosa ("no, borrá solo la de ayer"), no es una respuesta. Lo que no coincide
con estas variantes lo interpreta la IA, con la pregunta pendiente como contexto (paso 8.5 del
plan): si cancela, se cancela; si no, el mensaje sigue su camino normal.
"""

import re
from collections.abc import Sequence
from datetime import date

from app.infra.texto import sin_tildes

# Expresiones de varias palabras que cuentan como una sola.
_JUNTAS = {"de una": "deuna", "por favor": "porfa", "mejor no": "no", "ni loco": "no"}

# Palabras que deciden la respuesta.
_SI = {
    "si", "sii", "sip", "dale", "ok", "okey", "okay", "oka", "deuna", "confirmo", "confirmar",
    "confirmado", "confirma", "obvio", "claro", "correcto", "afirmativo", "adelante", "hacelo",
    "borra", "borrar", "borralo", "borrala", "borralos", "borralas", "borrame", "borrarlos",
}  # fmt: skip
_NO = {
    "no", "nop", "nono", "nah", "cancelar", "cancela", "cancelalo", "cancelo", "deja", "dejalo",
    "dejala", "dejalos", "dejalas", "nada", "negativo", "frena", "para", "olvidalo", "olvidate",
}  # fmt: skip
# Las del no que cancelan todo, también cuando el *no* tiene otro sentido ("¿*Omu* es *El
# Ombú*?": "no" es que es otro campo; "no, dejá", que no anote nada).
_CANCELAR = {
    "cancelar", "cancela", "cancelalo", "cancelo", "deja", "dejalo", "dejala", "dejalos", "dejalas",
    "nada", "frena", "para", "olvidalo", "olvidate",
}  # fmt: skip
# Palabras que pueden acompañarlas sin cambiar nada.
_RELLENO = {"bueno", "listo", "che", "gracias", "porfa", "ya", "eso", "ahi"}
_RELLENO_SI = {"todo", "todos", "todas", "nomas", "igual", "asi", "es", "ese", "esa", "el", "la", "mismo", "misma"}
_RELLENO_NO = {
    "borres", "toques", "toque", "asi", "como", "esta", "estan", "estaba", "por", "ahora", "todavia", "mejor",
    "nomas", "quiero", "queria", "cambiar", "cambies", "cambio", "hagas", "hacer", "lo", "la", "es", "otro",
    "otra", "ninguno", "ninguna",
}  # fmt: skip


def _palabras(texto: str) -> list[str]:
    limpio = " ".join(re.findall(r"[a-z]+", sin_tildes(texto.lower())))
    for juntas, una in _JUNTAS.items():
        limpio = re.sub(rf"\b{juntas}\b", una, limpio)
    return limpio.split()


def _es(texto: str, decisivas: set[str], relleno: set[str]) -> bool:
    palabras = _palabras(texto)
    return any(p in decisivas for p in palabras) and all(p in decisivas | relleno | _RELLENO for p in palabras)


def es_si(texto: str) -> bool:
    return _es(texto, _SI, _RELLENO_SI)


def es_no(texto: str) -> bool:
    return _es(texto, _NO, _RELLENO_NO)


def es_cancelar(texto: str) -> bool:
    """Un *no* que cancela la pregunta entera ("no, dejá", "cancelá", "olvidate")."""
    return es_no(texto) and any(p in _CANCELAR for p in _palabras(texto))


# "¿*El Ombú* es *Omu*?": *cambiale el nombre* (Omu pasa a llamarse El Ombú).
_RENOMBRAR = {"nombre", "renombra", "renombralo", "renombrar", "renombrarlo"}
_RELLENO_RENOMBRAR = {
    "cambia", "cambiale", "cambialo", "cambiar", "cambiarle", "ponele", "pone", "poner", "si", "dale", "ok",
    "mejor", "el", "la", "al", "a", "de", "del", "que", "se", "llame", "llama", "le", "lo", "su", "nuevo", "por",
    "ese", "es", "campo",
}  # fmt: skip


def es_renombrar(texto: str, nombres: Sequence[str]) -> bool:
    """*cambiale el nombre* a la pregunta de un campo parecido: todas las palabras tienen que
    ser de esa respuesta, de los nombres de los dos campos (`nombres`) o del relleno, y sin
    ningún *no* ("no, no le cambies el nombre, El Ombú es otro campo" no es)."""
    de_los_nombres = {p for nombre in nombres for p in _palabras(nombre)}
    palabras = _palabras(texto)
    if any(p in _NO for p in palabras):
        return False
    return any(p in _RENOMBRAR for p in palabras) and all(
        p in _RENOMBRAR | _RELLENO_RENOMBRAR | _RELLENO | de_los_nombres for p in palabras
    )


_DIAS_SEMANA = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
    "noviembre", "diciembre",
)  # fmt: skip
_RELLENO_FECHA = {"el", "la", "de", "del", "para", "es", "era", "opcion", "numero", "dia", "si", "dale", "ok", "mejor"}


def cual_fecha(texto: str, opciones: Sequence[date]) -> int | None:
    """Cuál de las fechas que se le mostraron eligió ("1", "la 2", "el jueves", "el 23", "vie
    23/10"); None si no es una respuesta o no señala una sola."""
    palabras = re.findall(r"[a-z]+|\d+", sin_tildes(texto.lower()))
    decisivas = [p for p in palabras if p not in _RELLENO_FECHA | _RELLENO]
    if len(decisivas) == 1 and decisivas[0] in ("1", "2") and len(opciones) == 2:
        return int(decisivas[0]) - 1

    def coincide(f: date, palabra: str) -> bool:
        if palabra.isdigit():
            return int(palabra) in (f.day, f.month, f.year)
        if palabra in _DIAS_SEMANA:
            return _DIAS_SEMANA.index(palabra) == f.weekday()
        if palabra in _MESES:
            return _MESES.index(palabra) + 1 == f.month
        # "vie", "jue": el día abreviado, como se muestra en las opciones
        return palabra == _DIAS_SEMANA[f.weekday()][:3]

    elegidas = [i for i, f in enumerate(opciones) if decisivas and all(coincide(f, p) for p in decisivas)]
    return elegidas[0] if len(elegidas) == 1 else None
