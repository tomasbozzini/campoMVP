"""Qué sitios se aceptan como fuente de datos: organismos oficiales y mercados regulados."""

from urllib.parse import urlparse

# Solo se aceptan precios cuyo link sea de uno de estos dominios (o subdominios).
DOMINIOS_OFICIALES = (
    "gob.ar",  # Secretaría de Agricultura, SENASA, INTA, datos.gob.ar...
    "bcr.com.ar",  # Bolsa de Comercio de Rosario y su Cámara Arbitral
    "mercadoagroganadero.com.ar",  # Mercado Agroganadero de Cañuelas
    "matba-rofex.com.ar",
    "a3mercados.com.ar",
    "bolsadecereales.com",  # Bolsa de Cereales de Buenos Aires
    "bcp.org.ar",  # Bolsa de Cereales y Productos de Bahía Blanca
)


def es_oficial(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return urlparse(url).scheme == "https" and any(host == d or host.endswith("." + d) for d in DOMINIOS_OFICIALES)
