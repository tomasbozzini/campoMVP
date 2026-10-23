"""Palabras del módulo común que Whisper tiene que escribir bien al transcribir un audio.

Van las que suele errar o escribir de otra forma: categorías de hacienda, manejo, sanidad,
labores y granos. Las que transcribe bien solo (vacas, lote, trigo) no hacen falta.

Ivermectina, aftosa, brucelosis, tacto, manga y destete pasaron al glosario de ganadería
(paso 2 de la etapa 2). Fumigación, fertilización, girasol y sorgo pasan al de agricultura
cuando exista (etapa 3).
"""

GLOSARIO = (
    "vaquillonas",
    "novillos",
    "terneros",
    "caravana",
    "rodeo",
    "potrero",
    "parición",
    "inseminación",
    "desparasitación",
    "SENASA",
    "fumigación",
    "fertilización",
    "girasol",
    "sorgo",
    "cebada",
)
