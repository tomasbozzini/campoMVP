"""Lo que recibe el manejador de una acción: quién escribió, qué escribió y su cuaderno."""

from dataclasses import dataclass
from datetime import date
from functools import cached_property

from sqlalchemy.orm import Session

from app.infra.modelos import Usuario
from app.nucleo.cuaderno import Cuaderno


@dataclass
class Contexto:
    db: Session
    usuario: Usuario
    texto: str  # el mensaje tal como llegó (o la transcripción del audio)
    hoy: date

    @cached_property
    def cuaderno(self) -> Cuaderno:
        return Cuaderno(self.db, self.usuario.id)
