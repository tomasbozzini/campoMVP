"""Servidor web: arma la app de FastAPI con sus rutas.  uvicorn app.main:app"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import paginas, webhook
from app.infra import db
from app.infra.config import config
from app.infra.logs import configurar_logs

configurar_logs()


def verificar_configuracion() -> None:
    """En producción, sin las claves de Meta y Groq el servidor no arranca."""
    if config.es_produccion and (faltan := config.faltantes_para_produccion()):
        raise RuntimeError(
            "Faltan variables de entorno obligatorias en producción: "
            + ", ".join(faltan)
            + ". Configuralas, o usá ENTORNO=desarrollo para probar en tu compu."
        )


@asynccontextmanager
async def _ciclo_de_vida(_app: FastAPI) -> AsyncIterator[None]:
    verificar_configuracion()
    db.crear_tablas()
    yield


app = FastAPI(title="Asistente de campo", lifespan=_ciclo_de_vida)
app.include_router(paginas.rutas)
app.include_router(webhook.rutas)
