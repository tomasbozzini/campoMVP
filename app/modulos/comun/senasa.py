"""Verificación de productos veterinarios en el registro oficial de SENASA.

El bot NO informa precios de medicamentos ni de instrumental, ni indicaciones de uso:
solo dice si un producto figura en el registro de SENASA, con su número de registro,
titular y estado, y de qué fecha son los datos.
"""

from typing import Annotated

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.fuentes.senasa import normalizar
from app.ia.esquemas import Esquema, EsquemaAccion, texto
from app.infra import modelos
from app.nucleo.acciones import Accion
from app.nucleo.contexto import Contexto

MAX_RESULTADOS = 5
AVISO = "_Solo verifica el registro en SENASA. No es una indicación de uso ni una recomendación._"


def buscar(db: Session, texto: str) -> list[modelos.ProductoVeterinario]:
    clave = normalizar(texto)
    if not clave or len(clave) < 3:
        return []
    patron = f"%{clave}%"
    q = select(modelos.ProductoVeterinario).where(
        or_(
            modelos.ProductoVeterinario.nombre_busqueda.like(patron),
            modelos.ProductoVeterinario.principio_busqueda.like(patron),
        )
    )
    return list(db.scalars(q.order_by(modelos.ProductoVeterinario.nombre).limit(MAX_RESULTADOS + 1)).all())


def responder(db: Session, texto: str | None) -> str:
    productos = buscar(db, texto or "")
    hay_registro = db.scalar(select(modelos.ProductoVeterinario).limit(1))
    if hay_registro is None:
        return "📭 Todavía no tengo cargado el registro de productos veterinarios de SENASA."
    if not productos:
        # Mensaje fijo: no repetimos lo que escribió la IA.
        return (
            "🔍 No encontré ese producto en el registro de SENASA que tengo cargado "
            f"(datos al {hay_registro.fecha_datos.strftime('%d/%m/%Y')}).\n"
            "Que no aparezca acá no confirma que no esté registrado. Podés verificarlo en:\n"
            f"{hay_registro.url}"
        )
    lineas = ["🔎 *REGISTRO SENASA*", ""]
    for p in productos[:MAX_RESULTADOS]:
        lineas.append(f"💊 *{p.nombre}*")
        lineas.append(f"      N° de registro: *{p.registro}*")
        if p.titular:
            lineas.append(f"      🏭 {p.titular}")
        if p.principio_activo:
            lineas.append(f"      🧪 {p.principio_activo}")
        estado = (p.estado or "").lower()
        icono = "✅" if estado == "vigente" else ("❔" if not estado else "⚠️")
        lineas.append(f"      {icono} Estado: {p.estado or 'no informado'}")
        lineas.append("")
    if len(productos) > MAX_RESULTADOS:
        lineas.append("_Hay más coincidencias. Escribí el nombre más completo._\n")
    primero = productos[0]
    lineas.append("────────────")
    lineas.append(f"📰 _Fuente: {primero.fuente}, datos al {primero.fecha_datos.strftime('%d/%m/%Y')}_")
    lineas.append(f"🔗 {primero.url}\n")
    return "\n".join(lineas) + "\n" + AVISO


# --- Acción "producto_veterinario" ---------------------------------------------


class Producto(Esquema):
    # Nombre comercial o principio activo, tal como lo escribió.
    nombre: Annotated[str | None, texto(80)] = None


class ProductoVeterinario(EsquemaAccion):
    producto_veterinario: Producto


def manejar(ctx: Contexto, datos: ProductoVeterinario) -> str:
    if not datos.producto_veterinario.nombre:
        return "¿Qué producto querés verificar en SENASA? Decime el nombre comercial o el principio activo."
    return responder(ctx.db, datos.producto_veterinario.nombre)


ACCION = Accion("producto_veterinario", ProductoVeterinario, manejar)
