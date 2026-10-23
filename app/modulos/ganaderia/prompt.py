"""Lo que el módulo ganadero le suma al prompt. Por ahora nada: tacto, raspaje y sanidad
llegan en los pasos 3 a 5 de la etapa 2, cada uno con su intención, sus campos y sus reglas.
Hasta entonces el prompt del veterinario y el del productor es el del módulo común."""

from app.ia.prompt import Parte

PROMPT = Parte(intenciones=(), campos="", descripciones="")
