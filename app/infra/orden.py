"""Procesar en orden: los trabajos de una misma persona, de a uno y en el orden en que
llegaron; los de personas distintas, en paralelo.

Sin esto, dos mensajes seguidos del mismo número (por ejemplo, "borrá todo" y "sí")
podrían procesarse a la vez en hilos distintos y pisarse.

Funciona dentro de un proceso, que es como corre el bot hoy (una sola instancia). Con
varias instancias habría que pasar el orden a la base o a una cola externa.
"""

import logging
import threading
from collections import deque
from collections.abc import Callable

log = logging.getLogger(__name__)

Trabajo = Callable[[], None]


class FilaPorClave:
    def __init__(self) -> None:
        self._candado = threading.Lock()
        # Claves con un hilo trabajando; la fila tiene lo que espera detrás.
        self._esperando: dict[str, deque[Trabajo]] = {}

    def ejecutar(self, clave: str, trabajo: Trabajo) -> None:
        """Ejecuta el trabajo ahora, o lo deja en la fila si ya hay uno de esa clave en
        curso: el hilo que lo está atendiendo lo ejecuta cuando termine el anterior."""
        with self._candado:
            if clave in self._esperando:
                self._esperando[clave].append(trabajo)
                return
            self._esperando[clave] = deque()
        siguiente: Trabajo | None = trabajo
        while siguiente is not None:
            try:
                siguiente()
            except Exception:
                log.exception("Falló un trabajo en la fila")
            with self._candado:
                fila = self._esperando[clave]
                if fila:
                    siguiente = fila.popleft()
                else:
                    del self._esperando[clave]
                    siguiente = None

    def en_curso(self) -> int:
        with self._candado:
            return len(self._esperando)
