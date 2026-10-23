"""Módulo ganadero, para veterinarios y productores: tacto y cierre, raspaje y sanidad
(etapa 2 de docs/arquitectura.md). Por ahora solo trae su glosario; las acciones llegan en los
pasos 3 a 5."""

from app.modulos.ganaderia.glosario import GLOSARIO
from app.modulos.ganaderia.prompt import PROMPT
from app.nucleo.acciones import Accion

ACCIONES: list[Accion] = []

__all__ = ["ACCIONES", "GLOSARIO", "PROMPT"]
