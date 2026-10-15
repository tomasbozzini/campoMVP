"""Utilidades de texto que usan varias partes del código."""

import re
import unicodedata

# Palabras que van en minúscula dentro de un nombre o un lugar ("25 de Mayo").
_PARTICULAS = {"de", "del", "la", "las", "los", "el", "y", "e", "da", "di", "van", "von"}
_INICIAL = re.compile(r"(^|[-'])(\w)")


def sin_tildes(texto: str) -> str:
    """'Maíz' -> 'Maiz', 'Ñandú' -> 'Nandu'. Para comparar lo que escribe la gente."""
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def prolijo(texto: str) -> str:
    """Para nombres y lugares: '  tres   ARROYOS ' -> 'Tres Arroyos'; '25 de mayo' -> '25 de Mayo'."""
    palabras = texto.lower().split()
    return " ".join(
        p if i > 0 and p in _PARTICULAS else _INICIAL.sub(lambda m: m.group(1) + m.group(2).upper(), p)
        for i, p in enumerate(palabras)
    )
