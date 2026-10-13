"""Los tests no dependen de la configuración de la compu donde corren."""

import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).parent.parent
PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]


def test_los_tests_no_leen_las_variables_de_entorno_del_sistema():
    """Con las variables del bot exportadas en la terminal, los tests dan lo mismo."""
    entorno = {
        **os.environ,
        "META_APP_SECRET": "secreto-exportado",
        "ENTORNO": "produccion",
        "ADMIN_TELEFONOS": "5499999999999",
        "LIMITE_DIARIO_IA": "1",
        "GROQ_MODELO": "",
    }
    resultado = subprocess.run(
        [*PYTEST, "tests/test_seguridad.py", "tests/test_orden.py"],
        cwd=RAIZ,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert resultado.returncode == 0, resultado.stdout[-3000:]
