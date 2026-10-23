"""Módulo ganadero, para veterinarios y productores: tacto y cierre, raspaje y sanidad
(etapa 2 de docs/arquitectura.md). Por ahora el tacto y el raspaje; sanidad llega en el paso 5."""

from app.modulos.comun import exportar
from app.modulos.ganaderia import raspaje, tacto
from app.modulos.ganaderia.glosario import GLOSARIO
from app.modulos.ganaderia.prompt import PROMPT
from app.nucleo import sesiones
from app.salidas import whatsapp as formato

ACCIONES = [tacto.ACCION, raspaje.ACCION]

# Lo que el tacto y el raspaje guardan en `extra` se ve en sus registros y en el resumen de la
# sesión; el raspaje tiene su PDF ("Registro de raspajes").
formato.DETALLES["tacto"] = tacto.detalle
formato.DETALLES[raspaje.TIPO] = raspaje.detalle
formato.ICONOS_TIPO.setdefault(raspaje.TIPO, "🔬")
sesiones.BLOQUES_RESUMEN["tacto"] = tacto.bloque_sesion
sesiones.BLOQUES_RESUMEN[raspaje.TIPO] = raspaje.bloque_sesion
exportar.PDFS[raspaje.TIPO] = (raspaje.NOMBRE_PDF, raspaje.armar_pdf)

__all__ = ["ACCIONES", "GLOSARIO", "PROMPT"]
