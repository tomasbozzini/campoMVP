"""El Dockerfile arranca el bot como lo necesita el código."""

from pathlib import Path

DOCKERFILE = (Path(__file__).parent.parent / "Dockerfile").read_text(encoding="utf-8")


def test_un_solo_worker_de_uvicorn():
    """La fila que ordena los mensajes de cada persona es por proceso (app/infra/orden.py), y
    uvicorn arranca varios si está definida WEB_CONCURRENCY: se fija en 1."""
    comando = next(linea for linea in DOCKERFILE.splitlines() if linea.startswith("CMD"))
    assert "--workers 1" in comando


def test_migra_antes_de_arrancar():
    """El servidor no migra solo (no arranca si falta migrar): lo hace el comando de arranque."""
    comando = next(linea for linea in DOCKERFILE.splitlines() if linea.startswith("CMD"))
    assert "python -m app db migrar && uvicorn" in comando
