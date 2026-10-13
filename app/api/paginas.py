"""Páginas públicas: salud del servidor y política de privacidad."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.salidas import privacidad

rutas = APIRouter()


@rutas.get("/")
def salud() -> dict:
    return {"ok": True}


@rutas.get("/privacidad", response_class=HTMLResponse)
def politica_de_privacidad() -> str:
    """Página pública con la política de privacidad (Meta la pide para publicar la app)."""
    return privacidad.html()
