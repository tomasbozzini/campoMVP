"""Lo que recibe el manejador de una acción: quién escribió, qué escribió y su cuaderno."""

from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cached_property

from sqlalchemy.orm import Session

from app.infra.modelos import Usuario
from app.nucleo.cuaderno import Cuaderno


@dataclass(frozen=True)
class Adjunto:
    """Un archivo que va con la respuesta (un PDF, una planilla)."""

    nombre: str  # como le llega a la persona: "CampoBot-registros-2026-10-16.pdf"
    contenido: bytes
    tipo: str  # "application/pdf"


@dataclass
class Contexto:
    db: Session
    usuario: Usuario
    texto: str  # el mensaje tal como llegó (o la transcripción del audio)
    hoy: date
    ahora: datetime  # en UTC: para las sesiones
    # False si la respuesta trae datos personales que la IA no necesita (no va a la charla).
    guardar_charla: bool = True
    # Los archivos que se mandan después del texto de la respuesta.
    adjuntos: list[Adjunto] = field(default_factory=list)
    # La pregunta del bot que esperaba respuesta y este mensaje no contestó (`nucleo/preguntas.py`):
    # la IA la recibe como contexto, por si el mensaje la cancela.
    pregunta_abierta: str | None = None

    @cached_property
    def cuaderno(self) -> Cuaderno:
        return Cuaderno(self.db, self.usuario)
