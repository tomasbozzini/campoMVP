"""Set de evaluación contra la IA real (`python -m app eval`).

Cada frase de `evaluacion/set.json` va al modelo con el prompt de un rubro y se compara la
lista de intenciones que devuelve, en orden, con la esperada. Una frase puede traer la charla
reciente ("historial", como la ve la IA) y la pregunta del bot que quedó sin contestar
("pregunta", una clave de `nucleo/preguntas.py`). Se mide lo que cuesta: tokens,
costo (si el proveedor lo informa) y demora. Frena si el costo acumulado llega al tope.
"""

import json
import math
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.ia import prompt
from app.ia.proveedor import ErrorIA, ProveedorTexto, Uso, medir

SET = Path(__file__).resolve().parents[2] / "evaluacion" / "set.json"


@dataclass(frozen=True)
class Frase:
    funcion: str
    frase: str
    intenciones: tuple[str, ...]
    historial: tuple[tuple[str, str], ...] = ()  # (rol, texto): "usuario" o "bot"
    pregunta: str | None = None


@dataclass
class Resultado:
    frase: Frase
    obtenidas: tuple[str, ...] = ()
    error: str | None = None
    usos: list[Uso] = field(default_factory=list)
    segundos: float = 0.0

    @property
    def bien(self) -> bool:
        return self.error is None and self.obtenidas == self.frase.intenciones

    @property
    def costo_usd(self) -> float:
        return sum(u.costo_usd or 0.0 for u in self.usos)


@dataclass(frozen=True)
class Resumen:
    total: int  # una llamada por frase (sin respaldo)
    bien: int
    errores: int  # llamadas que fallaron (límite, sin respuesta, JSON inválido)
    tokens_entrada: int
    tokens_salida: int
    tokens_razonamiento: int
    costo_usd: float | None  # None si el proveedor no informa el costo
    mediana: float
    p95: float

    @property
    def precision(self) -> float:
        return self.bien / self.total if self.total else 0.0


def cargar(ruta: Path = SET) -> list[Frase]:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return [
        Frase(
            f["funcion"],
            f["frase"],
            tuple(f["intenciones"]),
            tuple((rol, texto) for rol, texto in f.get("historial", [])),
            f.get("pregunta"),
        )
        for f in datos["frases"]
    ]


def elegir(
    frases: Sequence[Frase], funciones: Sequence[str] = (), desde: int = 1, limite: int | None = None
) -> list[Frase]:
    """Una parte del set: las de esas funciones (todas si no se dice), desde la número
    `desde` (contando desde 1) y hasta `limite` frases."""
    elegidas = [f for f in frases if not funciones or f.funcion in funciones][max(desde, 1) - 1 :]
    return elegidas if limite is None else elegidas[:limite]


def intenciones(interpretado: object) -> tuple[str, ...]:
    """Las intenciones de la respuesta del modelo, en orden (como las lee el núcleo)."""
    if not isinstance(interpretado, dict):
        return ()
    crudas = interpretado.get("acciones")
    lista = crudas if isinstance(crudas, list) else [interpretado]
    return tuple(str(a.get("intencion")) for a in lista if isinstance(a, dict))


def correr(
    frases: Sequence[Frase],
    proveedor: ProveedorTexto,
    partes: Sequence[prompt.Parte],
    hoy: date,
    tope_usd: float,
    pausa: float = 0.0,
    al_terminar: Callable[[Resultado], None] = lambda _r: None,
    preguntas: Mapping[str, str] | None = None,
) -> tuple[list[Resultado], bool]:
    """Corre las frases de a una. Devuelve los resultados y si frenó por el tope de costo.
    `preguntas`: el texto que ve la IA para cada clave de pregunta pendiente."""
    sistema = prompt.sistema(hoy, partes)
    resultados: list[Resultado] = []
    gastado = 0.0
    for i, frase in enumerate(frases):
        if i and pausa:
            time.sleep(pausa)
        resultado = Resultado(frase)
        inicio = time.perf_counter()
        with medir() as usos:
            try:
                pregunta = (preguntas or {}).get(frase.pregunta or "")
                mensaje = prompt.mensaje(frase.frase, frase.historial, pregunta)
                resultado.obtenidas = intenciones(proveedor.completar_json(sistema, mensaje))
            except ErrorIA as e:
                resultado.error = str(e)
        resultado.segundos = time.perf_counter() - inicio
        resultado.usos = usos
        resultados.append(resultado)
        al_terminar(resultado)
        gastado += resultado.costo_usd
        if gastado >= tope_usd and i < len(frases) - 1:
            return resultados, True
    return resultados, False


def _p95(valores: list[float]) -> float:
    """Percentil 95 por rango más cercano: el valor que deja abajo al 95 % de las mediciones."""
    ordenados = sorted(valores)
    return ordenados[math.ceil(0.95 * len(ordenados)) - 1] if ordenados else 0.0


def resumir(resultados: Sequence[Resultado]) -> Resumen:
    usos = [u for r in resultados for u in r.usos]
    demoras = [r.segundos for r in resultados]
    con_costo = [u.costo_usd for u in usos if u.costo_usd is not None]
    return Resumen(
        total=len(resultados),
        bien=sum(r.bien for r in resultados),
        errores=sum(r.error is not None for r in resultados),
        tokens_entrada=sum(u.tokens_entrada for u in usos),
        tokens_salida=sum(u.tokens_salida for u in usos),
        tokens_razonamiento=sum(u.tokens_razonamiento for u in usos),
        costo_usd=sum(con_costo) if con_costo else None,
        mediana=statistics.median(demoras) if demoras else 0.0,
        p95=_p95(demoras),
    )
