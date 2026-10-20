"""Cómo se normalizan los nombres de lotes y establecimientos, para guardar y buscar igual."""

from difflib import SequenceMatcher

from app.infra.texto import sin_tildes


def normalizar_lote(lote: object) -> str | None:
    """'Lote 3' -> '3', 'el lote 5' -> '5', 'Potrero Grande' -> 'potrero grande'."""
    if not lote:
        return None
    texto = str(lote).strip().lower()
    for prefijo in ("el lote ", "lote ", "lote n°", "lote nro "):
        if texto.startswith(prefijo):
            texto = texto[len(prefijo) :].strip()
    return texto or None


def clave_establecimiento(nombre: str | None) -> str | None:
    """ "Estancia La Esperanza", "la esperanza" y "La Esperanza" son el mismo lugar."""
    if not nombre:
        return None
    texto = sin_tildes(nombre.strip().lower())
    for prefijo in ("estancia ", "establecimiento ", "campo ", "el campo "):
        if texto.startswith(prefijo):
            texto = texto[len(prefijo) :]
    return " ".join(texto.split()) or None


# Al comparar dos nombres de campo no cuentan los artículos del principio ("El Ombú" y "Ombú").
_ARTICULOS = ("el ", "la ", "los ", "las ")
# Desde qué parecido dos nombres pueden ser el mismo campo mal escrito o mal transcripto
# ("omu" y "ombu" dan 0,86; "santa rosa" y "santa rita", 0,8; "la pastora" y "la paloma", 0,6).
PARECIDO_MINIMO = 0.84


def sin_articulo(clave: str) -> str:
    """ "el ombu" -> "ombu"."""
    for articulo in _ARTICULOS:
        if clave.startswith(articulo):
            return clave[len(articulo) :]
    return clave


def parecido(clave: str, otra: str) -> float:
    """Qué tan parecidas son dos claves de establecimiento, de 0 a 1, sin los artículos."""
    a, b = sin_articulo(clave), sin_articulo(otra)
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()
