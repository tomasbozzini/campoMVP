"""Respuestas cortas a una pregunta del bot (*sí* / *no*), sin IA.

Además de "sí" y "no", se aceptan las variantes de siempre: "dale", "ok", "sí, borrá",
"de una", "no, dejá", "mejor no", "cancelá", "no, no, dejá, no quiero cambiar nada". Todas
las palabras tienen que ser de una respuesta del mismo lado: si mezcla un sí y un no ("dale,
no") o trae otra cosa ("no, borrá solo la de ayer"), no es una respuesta. Lo que no coincide
con estas variantes lo interpreta la IA, con la pregunta pendiente como contexto (paso 8.5 del
plan): si cancela, se cancela; si no, el mensaje sigue su camino normal.
"""

import re

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
