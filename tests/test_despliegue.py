"""El Dockerfile arranca el bot como lo necesita el código."""

import re
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


def test_los_comandos_del_readme_funcionan_en_cmd():
    """cmd no tiene comentarios al final de la línea: "python -m app precios ver soja  # ..."
    le pasa "#" y lo que sigue como argumentos. Los comandos van en bloques ```bat, sin #."""
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    bloques = re.findall(r"```(\w*)\n(.*?)```", readme, flags=re.DOTALL)
    assert not [b for lenguaje, b in bloques if lenguaje in ("bash", "sh", "shell", "console")]
    comandos = [linea for lenguaje, b in bloques if lenguaje == "bat" for linea in b.splitlines()]
    assert comandos
    assert [linea for linea in comandos if re.search(r"(^|\s)#", linea)] == []
