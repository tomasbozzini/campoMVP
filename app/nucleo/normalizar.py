"""Cómo se normalizan los nombres de lotes y establecimientos, para guardar y buscar igual."""

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
