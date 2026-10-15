"""Palabras del módulo común que Whisper tiene que escribir bien al transcribir un audio.

Van las que suele errar o escribir de otra forma: categorías de hacienda, manejo, sanidad,
labores y granos. Las que transcribe bien solo (vacas, lote, trigo) no hacen falta.

Cuando existan los módulos, pasan a su glosario (ver docs/arquitectura.md, etapas 2 y 3):
ivermectina, aftosa, brucelosis, tacto, manga y destete a ganadería; fumigación,
fertilización, girasol y sorgo a agricultura.
"""

GLOSARIO = (
    "vaquillonas",
    "novillos",
    "terneros",
    "caravana",
    "rodeo",
    "potrero",
    "manga",
    "tacto",
    "destete",
    "parición",
    "inseminación",
    "desparasitación",
    "ivermectina",
    "aftosa",
    "brucelosis",
    "SENASA",
    "fumigación",
    "fertilización",
    "girasol",
    "sorgo",
    "cebada",
)
