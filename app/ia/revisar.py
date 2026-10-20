"""Revisar las pruebas del modo prueba y sumarlas al set de evaluación (paso 9b del plan).

`python -m app eval revisar [--base URL]`: muestra de a una las pruebas que no están en el set
(el mensaje, la charla y la pregunta que vio la IA, lo que devolvió y lo que respondió el bot).
Lo aprobado se guarda solo en `evaluacion/set.json`; la base se lee en solo lectura. Lo
descartado queda en `evaluacion/descartadas.txt` (fuera del repo), solo como una huella de cada
prueba, para no volver a mostrarlo.
"""

import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ia.evaluacion import SET, Frase, intenciones
from app.infra.modelos import Prueba

DESCARTADAS = SET.parent / "descartadas.txt"
ORIGEN = "modo prueba"
LARGO_CHARLA = 300  # caracteres de cada mensaje de la charla que se muestran


def huella(prueba: Prueba) -> str:
    """Identifica una prueba sin guardar su texto."""
    clave = f"{prueba.usuario_id}|{prueba.id}|{prueba.texto}"
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()[:16]


def descartadas(ruta: Path = DESCARTADAS) -> set[str]:
    return set(ruta.read_text(encoding="utf-8").split()) if ruta.exists() else set()


def descartar(prueba: Prueba, ruta: Path = DESCARTADAS) -> None:
    with ruta.open("a", encoding="utf-8") as archivo:
        archivo.write(huella(prueba) + "\n")


def _charla(prueba: Prueba) -> tuple[tuple[str, str], ...]:
    return tuple((rol, texto) for rol, texto in prueba.historial)


def para_revisar(db: Session, frases: Sequence[Frase], ya_descartadas: set[str]) -> list[Prueba]:
    """Las pruebas que no están en el set (la misma frase con la misma charla) ni descartadas."""
    en_el_set = {(f.frase, f.historial) for f in frases}
    pruebas = db.scalars(select(Prueba).order_by(Prueba.id))
    return [p for p in pruebas if (p.texto, _charla(p)) not in en_el_set and huella(p) not in ya_descartadas]


def frase(prueba: Prueba, funcion: str, esperadas: Sequence[str], fechas: Sequence[str]) -> dict[str, Any]:
    """La frase para el set, como las demás: con la charla, la pregunta y, si hay fechas, el día."""
    nueva: dict[str, Any] = {"funcion": funcion, "frase": prueba.texto, "intenciones": list(esperadas)}
    if fechas:
        nueva["hoy"] = prueba.hoy.isoformat()
        nueva["fechas"] = list(fechas)
    if prueba.historial:
        nueva["historial"] = [list(par) for par in prueba.historial]
    if prueba.pregunta:
        nueva["pregunta"] = prueba.pregunta
    nueva["origen"] = ORIGEN
    return nueva


def agregar_al_set(nueva: dict[str, Any], ruta: Path = SET) -> None:
    """Suma la frase al final de la lista, una por línea como las demás, sin rearmar el archivo."""
    texto = ruta.read_text(encoding="utf-8")
    cierre = texto.rindex("\n  ]")
    linea = "    " + json.dumps(nueva, ensure_ascii=False)
    ruta.write_text(f"{texto[:cierre].rstrip()},\n{linea}{texto[cierre:]}", encoding="utf-8")
    json.loads(ruta.read_text(encoding="utf-8"))  # que siga siendo JSON válido


def mostrar(prueba: Prueba, numero: int, total: int, fechas: Sequence[str]) -> str:
    """Lo que se ve de una prueba en la terminal."""
    audio = " · 🎤 audio" if prueba.audio else ""
    lineas = [f"\n─── {numero} de {total} · {prueba.hoy:%d/%m/%Y}{audio}"]
    if prueba.historial:
        lineas.append("Charla que vio la IA:")
        lineas += [f"  {rol}: {texto[:LARGO_CHARLA]}" for rol, texto in prueba.historial]
    if prueba.pregunta:
        lineas.append(f"Pregunta abierta: {prueba.pregunta}")
    lineas.append(f"Mensaje: {prueba.texto}")
    lineas.append(f"La IA: {', '.join(intenciones(prueba.interpretacion)) or '(nada)'}")
    lineas.append(f"  {json.dumps(prueba.interpretacion, ensure_ascii=False)}")
    if fechas:
        lineas.append(f"Fechas calculadas: {', '.join(fechas)}")
    lineas.append("El bot respondió:")
    lineas += [f"  {linea}" for linea in prueba.respuesta.splitlines()]
    return "\n".join(lineas)


OPCIONES = "[a] aprobar · [c] corregir · [d] descartar · [s] saltar · [q] salir > "


def revisar(
    pruebas: Sequence[Prueba],
    fechas: Callable[[object, Any], tuple[str, ...]],
    es_intencion: Callable[[str], bool],
    leer: Callable[[str], str] | None = None,
    escribir: Callable[[str], None] | None = None,
    ruta_set: Path = SET,
    ruta_descartadas: Path = DESCARTADAS,
) -> tuple[int, int]:
    """La revisión en la terminal. Cada aprobada va al set en el momento (si se corta, no se
    pierde). Devuelve cuántas se aprobaron y cuántas se descartaron. `leer` y `escribir`: la
    terminal (`input` y `print`), salvo en los tests."""
    leer, escribir = leer or input, escribir or print
    aprobadas = descartadas_ahora = 0
    for numero, prueba in enumerate(pruebas, start=1):
        calculadas = fechas(prueba.interpretacion, prueba.hoy)
        escribir(mostrar(prueba, numero, len(pruebas), calculadas))
        while True:
            opcion = leer(OPCIONES).strip().lower()
            if opcion == "q":
                return aprobadas, descartadas_ahora
            if opcion in ("s", "d", "a", "c"):
                break
        if opcion == "s":
            continue
        if opcion == "d":
            descartar(prueba, ruta_descartadas)
            descartadas_ahora += 1
            continue
        esperadas, esperadas_fechas = list(intenciones(prueba.interpretacion)), list(calculadas)
        if opcion == "c":
            esperadas = _pedir_intenciones(leer, escribir, es_intencion)
            texto = leer("Fechas esperadas (YYYY-MM-DD, separadas por coma; vacío si no se controlan) > ")
            esperadas_fechas = [f.strip() for f in texto.split(",") if f.strip()]
        por_defecto = esperadas[0] if esperadas else "otros"
        funcion = leer(f"Función [{por_defecto}] > ").strip() or por_defecto
        agregar_al_set(frase(prueba, funcion, esperadas, esperadas_fechas), ruta_set)
        aprobadas += 1
        escribir(f"✓ Sumada al set como {funcion}.")
    return aprobadas, descartadas_ahora


def _pedir_intenciones(
    leer: Callable[[str], str], escribir: Callable[[str], None], es_intencion: Callable[[str], bool]
) -> list[str]:
    while True:
        nombres = [n.strip() for n in leer("Intenciones esperadas, en orden (separadas por coma) > ").split(",")]
        nombres = [n for n in nombres if n]
        malas = [n for n in nombres if not es_intencion(n)]
        if nombres and not malas:
            return nombres
        escribir(f"No conozco: {', '.join(malas)}" if malas else "Escribí al menos una.")
