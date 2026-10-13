"""Lo que comparten las acciones sobre registros del cuaderno: los datos de un registro
tal como los devuelve la IA, y cómo encontrar el registro al que se refiere la persona."""

from datetime import date
from typing import Annotated

from pydantic import BeforeValidator

from app.ia.esquemas import Decimal, Entero, Esquema, Fecha, texto
from app.infra.modelos import Evento
from app.nucleo.normalizar import clave_establecimiento, normalizar_lote
from app.salidas import whatsapp as formato

CATEGORIAS = {"sanidad", "movimiento", "pesada", "reproduccion", "campo"}

# "Lote 3" -> "3", como se guarda y se busca.
Lote = Annotated[str | None, BeforeValidator(normalizar_lote)]


class DatosEvento(Esquema):
    """Un registro como lo describe la IA, ya limpio. Mismos largos que las columnas."""

    categoria: Annotated[str | None, texto(20, minuscula=True)] = None
    tipo: Annotated[str | None, texto(30, minuscula=True)] = None
    descripcion: Annotated[str | None, texto(500)] = None
    producto: Annotated[str | None, texto(120)] = None
    dosis: Annotated[str | None, texto(60)] = None
    cantidad_animales: Entero = None
    categoria_animal: Annotated[str | None, texto(40, minuscula=True)] = None
    caravana: Annotated[str | None, texto(40)] = None
    lote: Lote = None
    lote_destino: Lote = None
    valor: Decimal = None
    unidad: Annotated[str | None, texto(20)] = None
    fecha_evento: Fecha = None
    confianza: Annotated[str | None, texto(10)] = None


def fecha_valida(fecha: date | None, hoy: date) -> date:
    """Un registro no puede ser del futuro ni quedar sin fecha: en esos casos, hoy."""
    return min(fecha, hoy) if fecha else hoy


class Referencia(Esquema):
    """Los datos con los que la persona identifica un registro que ya anotó
    ("esas 5 vaquillonas", "la lluvia de La Pastora")."""

    categoria: Annotated[str | None, texto(20)] = None
    tipo: Annotated[str | None, texto(30)] = None
    descripcion: Annotated[str | None, texto(500)] = None
    producto: Annotated[str | None, texto(120)] = None
    dosis: Annotated[str | None, texto(60)] = None
    cantidad_animales: Entero = None
    categoria_animal: Annotated[str | None, texto(40)] = None
    caravana: Annotated[str | None, texto(40)] = None
    lote: Lote = None
    lote_destino: Lote = None
    valor: Decimal = None
    unidad: Annotated[str | None, texto(20)] = None
    fecha_evento: Fecha = None
    confianza: Annotated[str | None, texto(10)] = None
    establecimiento: Annotated[str | None, texto(120)] = None
    desde: Fecha = None
    hasta: Fecha = None

    def tiene_datos(self) -> bool:
        return any(getattr(self, campo) is not None for campo in Referencia.model_fields)


def coincide(e: Evento, ref: Referencia) -> bool:
    """¿El registro tiene todos los datos con los que la persona lo identificó?
    (descripción, dosis, valor... no sirven para identificar y no se comparan)."""
    if ref.cantidad_animales is not None and e.cantidad_animales != ref.cantidad_animales:
        return False
    if ref.categoria_animal and (
        not e.categoria_animal or formato.singular(ref.categoria_animal.lower()) not in e.categoria_animal.lower()
    ):
        return False
    if ref.lote and e.lote != ref.lote:
        return False
    if ref.lote_destino and e.lote_destino != ref.lote_destino:
        return False
    if ref.establecimiento and e.establecimiento_clave != clave_establecimiento(ref.establecimiento):
        return False
    if ref.tipo and (e.tipo or "").lower() != ref.tipo.lower():
        return False
    if ref.caravana and (e.caravana or "").lower() != ref.caravana.lower():
        return False
    if ref.producto and ref.producto.lower() not in (e.producto or "").lower():
        return False
    if ref.categoria and e.categoria != ref.categoria.lower():
        return False
    if ref.desde and e.fecha_evento < ref.desde:
        return False
    if ref.hasta and e.fecha_evento > ref.hasta:
        return False
    return not (ref.fecha_evento and e.fecha_evento != ref.fecha_evento)


def describir(ref: Referencia) -> str:
    """Texto armado por el código (no por la IA) para describir lo que se buscó."""
    partes: list[str] = []
    if ref.tipo:
        partes.append(formato.nombre_tipo(ref.tipo.lower()))
    if ref.cantidad_animales:
        partes.append(str(ref.cantidad_animales))
    if ref.categoria_animal:
        partes.append(ref.categoria_animal)
    if ref.lote:
        partes.append(f"lote {ref.lote}")
    if ref.establecimiento:
        partes.append(f"en {ref.establecimiento[:60]}")
    return "_" + (" ".join(partes) or "eso") + "_"
