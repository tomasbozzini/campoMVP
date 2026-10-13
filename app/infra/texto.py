"""Utilidades de texto que usan varias partes del código."""

import unicodedata


def sin_tildes(texto: str) -> str:
    """'Maíz' -> 'Maiz', 'Ñandú' -> 'Nandu'. Para comparar lo que escribe la gente."""
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
