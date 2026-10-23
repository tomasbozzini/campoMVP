"""Módulo ganadero, para veterinarios y productores: tacto y cierre, raspaje y sanidad
(etapa 2 de docs/arquitectura.md). Por ahora el tacto; raspaje y sanidad llegan en los pasos 4
y 5."""

from app.modulos.ganaderia import tacto
from app.modulos.ganaderia.glosario import GLOSARIO
from app.modulos.ganaderia.prompt import PROMPT
from app.nucleo import sesiones
from app.salidas import whatsapp as formato

ACCIONES = [tacto.ACCION]

# Lo que el tacto guarda en `extra` se ve en sus registros y en el resumen de la sesión.
formato.DETALLES["tacto"] = tacto.detalle
sesiones.BLOQUES_RESUMEN["tacto"] = tacto.bloque_sesion

__all__ = ["ACCIONES", "GLOSARIO", "PROMPT"]
