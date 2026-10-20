"""Páginas públicas: salud del servidor y política de privacidad."""

from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.infra.config import config
from app.salidas import privacidad

rutas = APIRouter()


@rutas.get("/")
@rutas.get("/salud")
def salud() -> dict[str, Any]:
    """Responde si el servidor anda y qué commit corre, para ver que Railway desplegó el último."""
    return {"ok": True, "commit": config.railway_git_commit_sha[:7] or None}


@rutas.get("/privacidad", response_class=HTMLResponse)
def politica_de_privacidad() -> str:
    """Página pública con la política de privacidad (Meta la pide para publicar la app)."""
    return privacidad.html()
