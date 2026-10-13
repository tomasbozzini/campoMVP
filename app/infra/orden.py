"""Procesar en orden: los trabajos de una misma persona, de a uno y en el orden en que
llegaron; los de personas distintas, en paralelo.

Sin esto, dos mensajes seguidos del mismo número (por ejemplo, "borrá todo" y "sí")
podrían procesarse a la vez en hilos distintos y pisarse.

Quien recibe los mensajes los encola enseguida y en orden (`encolar` no espera a que se
procesen). Cada clave con trabajo pendiente tiene un hilo del pool que la atiende hasta
vaciar su fila; otra clave no lo espera.

Funciona dentro de un proceso, que es como corre el bot hoy (una sola instancia y un solo
worker de uvicorn). Con varias instancias habría que pasar el orden a la base o a una cola
externa.
"""

import logging
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

Trabajo = Callable[[], None]

# Personas atendidas a la vez. Si escriben más, esperan a que se libere un hilo (siempre
# en orden dentro de cada una). Por debajo de las 15 conexiones del pool de la base.
HILOS = 10


class FilaPorClave:
    def __init__(self, hilos: int = HILOS) -> None:
        self._hilos = ThreadPoolExecutor(max_workers=hilos, thread_name_prefix="fila")
        self._candado = threading.Lock()
        self._vacia = threading.Condition(self._candado)
        # Claves con un hilo asignado; la fila tiene lo que todavía no empezó.
        self._esperando: dict[str, deque[Trabajo]] = {}

    def encolar(self, clave: str, trabajo: Trabajo) -> None:
        """Deja el trabajo detrás de los de su clave, sin esperar a que se ejecute."""
        with self._candado:
            if clave in self._esperando:
                self._esperando[clave].append(trabajo)
                return
            self._esperando[clave] = deque([trabajo])
            self._lanzar(clave)

    def esperar(self, segundos: float | None = None) -> bool:
        """Espera a que no quede nada pendiente. False si pasó el tiempo y todavía queda."""
        with self._vacia:
            return self._vacia.wait_for(lambda: not self._esperando, segundos)

    def en_curso(self) -> int:
        with self._candado:
            return len(self._esperando)

    def _lanzar(self, clave: str) -> None:
        """Le asigna un hilo a la clave. Se llama con el candado tomado."""
        try:
            self._hilos.submit(self._atender, clave)
        except RuntimeError:  # el pool ya se cerró: el proceso está terminando
            log.error("No se pudo procesar la fila: el proceso está terminando")
            self._liberar(clave)

    def _liberar(self, clave: str) -> None:
        """Se llama con el candado tomado."""
        del self._esperando[clave]
        if not self._esperando:
            self._vacia.notify_all()

    def _siguiente(self, clave: str) -> Trabajo | None:
        with self._candado:
            fila = self._esperando[clave]
            return fila.popleft() if fila else None

    def _atender(self, clave: str) -> None:
        """El hilo de una clave: ejecuta sus trabajos de a uno hasta vaciar su fila."""
        try:
            while (trabajo := self._siguiente(clave)) is not None:
                try:
                    trabajo()
                except Exception:
                    log.exception("Falló un trabajo de la fila")
        finally:
            # También si una BaseException cortó el hilo: la clave nunca queda trabada.
            with self._candado:
                if self._esperando[clave]:
                    # Llegó algo justo al terminar, o se cortó con trabajo pendiente: sigue otro hilo.
                    self._lanzar(clave)
                else:
                    self._liberar(clave)
