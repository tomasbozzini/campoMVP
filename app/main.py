"""Servidor web: arma la app de FastAPI con sus rutas.  uvicorn app.main:app"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import modulos
from app.api import paginas, webhook
from app.infra import db, migrar
from app.infra.config import config
from app.infra.logs import configurar_logs

configurar_logs()
log = logging.getLogger(__name__)

# Al apagarse (por ejemplo, en un redeploy), cuánto se espera a que terminen los mensajes
# que ya se recibieron: Meta no los vuelve a mandar porque ya respondimos 200.
ESPERA_AL_CERRAR = 30  # segundos


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
    modulos.cargar()
    migrar.revisar(db.engine)  # no migra: eso lo hace solo `python -m app db migrar`
    yield
    if not webhook.fila.esperar(ESPERA_AL_CERRAR):
        log.warning("El servidor se apaga con %d personas con mensajes sin procesar", webhook.fila.en_curso())


app = FastAPI(title="Asistente de campo", lifespan=_ciclo_de_vida)
app.include_router(paginas.rutas)
app.include_router(webhook.rutas)
