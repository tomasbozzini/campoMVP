"""Acceso a los datos de UNA persona: el cuaderno de su cuenta (registros, establecimientos
y lotes), su charla con el bot, su cupo diario y los borrados que esperan confirmación.

Es la única puerta a esas tablas. Lo que se anota es de la cuenta y se filtra por la cuenta
de quien abrió el cuaderno (hoy, 1 persona = 1 cuenta); la charla, el cupo y los borrados
pendientes son de la conversación de cada persona y se filtran por usuario. No hay forma de
leer ni tocar lo de otra cuenta aunque un id venga mal. Fuera de este módulo nadie filtra
por `cuenta_id` ni por `usuario_id` a mano.
"""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.infra.modelos import (
    BorradoPendiente,
    Establecimiento,
    Evento,
    Lote,
    MensajeChat,
    Solicitud,
    UsoDiario,
    Usuario,
)
from app.nucleo import auditoria
from app.nucleo.normalizar import clave_establecimiento, normalizar_lote

# Tope de registros que devuelve una búsqueda.
MAX_EVENTOS = 5000


@dataclass(frozen=True)
class Campo:
    """Un establecimiento con sus lotes y cuántos registros tiene. Sin establecimiento: los
    lotes sueltos y los registros que no dicen dónde fueron."""

    establecimiento: Establecimiento | None
    lotes: list[str]
    registros: int


@dataclass(frozen=True)
class Filtros:
    """Filtros de búsqueda en el cuaderno. Los vacíos no filtran."""

    establecimiento_clave: str | None = None  # ya normalizado (normalizar.clave_establecimiento)
    categoria: str | None = None
    tipo: str | None = None
    lote: str | None = None  # ya normalizado (normalizar.normalizar_lote); busca origen o destino
    caravana: str | None = None
    categoria_animal: str | None = None
    producto: str | None = None  # en el producto o en la descripción
    desde: date | None = None
    hasta: date | None = None


class Cuaderno:
    def __init__(self, db: Session, usuario: Usuario) -> None:
        self.db = db
        self.usuario_id = usuario.id
        self.cuenta_id = usuario.cuenta_id

    # --- Registros ------------------------------------------------------------

    def agregar(self, eventos: list[Evento]) -> None:
        for evento in eventos:
            evento.cuenta_id = self.cuenta_id
            evento.usuario_id = self.usuario_id
            self.db.add(evento)
        self.db.flush()

    def recientes(self, limite: int) -> list[Evento]:
        """Los últimos registros anotados, del más nuevo al más viejo."""
        q = select(Evento).where(Evento.cuenta_id == self.cuenta_id).order_by(Evento.id.desc()).limit(limite)
        return list(self.db.scalars(q).all())

    def ultimo(self) -> Evento | None:
        return next(iter(self.recientes(1)), None)

    def del_mensaje(self, mensaje_id: str) -> list[Evento]:
        """Los registros que se anotaron juntos, con un mismo mensaje."""
        q = select(Evento).where(Evento.cuenta_id == self.cuenta_id, Evento.mensaje_id == mensaje_id)
        return list(self.db.scalars(q).all())

    def cantidad(self) -> int:
        return self.db.scalar(select(func.count(Evento.id)).where(Evento.cuenta_id == self.cuenta_id)) or 0

    def borrar(self, ids: list[int]) -> int:
        """Borra esos registros, solo si son de esta cuenta. Devuelve cuántos borró."""
        resultado = self.db.execute(delete(Evento).where(Evento.id.in_(ids), Evento.cuenta_id == self.cuenta_id))
        borrados = int(getattr(resultado, "rowcount", 0) or 0)
        if borrados:
            auditoria.registrar(
                self.db, auditoria.BORRAR_REGISTROS, actor=self.usuario_id, cuenta=self.cuenta_id, cantidad=borrados
            )
        return borrados

    def buscar(self, filtros: Filtros) -> list[Evento]:
        """Busca con los filtros que armó el código a partir de lo que pidió la IA. El
        modelo nunca escribe SQL ni ve los resultados."""
        q = select(Evento).where(Evento.cuenta_id == self.cuenta_id)
        if filtros.establecimiento_clave:
            campo = select(Establecimiento.id).where(
                Establecimiento.cuenta_id == self.cuenta_id, Establecimiento.clave == filtros.establecimiento_clave
            )
            q = q.where(Evento.establecimiento_id.in_(campo))
        if filtros.categoria:
            q = q.where(Evento.categoria == filtros.categoria.lower())
        if filtros.tipo:
            q = q.where(Evento.tipo == filtros.tipo.lower())
        if filtros.lote:
            # El lote de cualquier campo, como origen o como destino.
            lotes = select(Lote.id).where(Lote.cuenta_id == self.cuenta_id, Lote.nombre == filtros.lote)
            q = q.where(Evento.lote_id.in_(lotes) | Evento.lote_destino_id.in_(lotes))
        if filtros.caravana:
            q = q.where(func.lower(Evento.caravana) == filtros.caravana.lower())
        if filtros.categoria_animal:
            raiz = filtros.categoria_animal.lower().rstrip("s")
            q = q.where(func.lower(Evento.categoria_animal).like(f"%{raiz}%"))
        if filtros.producto:
            texto = f"%{filtros.producto.lower()}%"
            q = q.where(func.lower(Evento.producto).like(texto) | func.lower(Evento.descripcion).like(texto))
        if filtros.desde:
            q = q.where(Evento.fecha_evento >= filtros.desde)
        if filtros.hasta:
            q = q.where(Evento.fecha_evento <= filtros.hasta)
        q = q.order_by(Evento.fecha_evento.desc(), Evento.id.desc()).limit(MAX_EVENTOS)
        return list(self.db.scalars(q).all())

    # --- Establecimientos y lotes ---------------------------------------------

    def establecimiento(self, nombre: str | None) -> Establecimiento | None:
        """El establecimiento con ese nombre, escrito como sea ("Estancia La Esperanza", "la
        esperanza"). Si es la primera vez que lo nombra, se crea con el nombre como lo escribió."""
        clave = clave_establecimiento(nombre)
        if not nombre or not clave:
            return None
        existente = self.db.scalar(
            select(Establecimiento).where(Establecimiento.cuenta_id == self.cuenta_id, Establecimiento.clave == clave)
        )
        if existente is not None:
            return existente
        nuevo = Establecimiento(cuenta_id=self.cuenta_id, nombre=" ".join(nombre.split()), clave=clave)
        self.db.add(nuevo)
        self.db.flush()
        return nuevo

    def lote(self, nombre: str | None, establecimiento: Establecimiento | None) -> Lote | None:
        """El lote con ese nombre en ese establecimiento (o suelto, sin establecimiento). Si no
        existe, se crea. El establecimiento tiene que ser de esta cuenta."""
        limpio = normalizar_lote(nombre)
        if not limpio:
            return None
        if establecimiento is not None and establecimiento.cuenta_id != self.cuenta_id:
            raise ValueError("El establecimiento es de otra cuenta")
        establecimiento_id = establecimiento.id if establecimiento else None
        existente = self.db.scalar(
            select(Lote).where(
                Lote.cuenta_id == self.cuenta_id,
                Lote.establecimiento_id.is_(None)
                if establecimiento_id is None
                else Lote.establecimiento_id == establecimiento_id,
                Lote.nombre == limpio,
            )
        )
        if existente is not None:
            return existente
        nuevo = Lote(cuenta_id=self.cuenta_id, establecimiento_id=establecimiento_id, nombre=limpio)
        self.db.add(nuevo)
        self.db.flush()
        return nuevo

    def campos(self) -> list[Campo]:
        """Los establecimientos por nombre, con sus lotes y cuántos registros tiene cada uno.
        Al final, lo que no tiene establecimiento (si hay algo)."""
        establecimientos = self.db.scalars(
            select(Establecimiento).where(Establecimiento.cuenta_id == self.cuenta_id).order_by(Establecimiento.clave)
        ).all()
        lotes: dict[int | None, list[str]] = {}
        for establecimiento_id, nombre in self.db.execute(
            select(Lote.establecimiento_id, Lote.nombre).where(Lote.cuenta_id == self.cuenta_id)
        ):
            lotes.setdefault(establecimiento_id, []).append(nombre)
        registros: dict[int | None, int] = dict(
            self.db.execute(
                select(Evento.establecimiento_id, func.count(Evento.id))
                .where(Evento.cuenta_id == self.cuenta_id)
                .group_by(Evento.establecimiento_id)
            ).all()
        )
        campos = [Campo(e, _ordenar_lotes(lotes.get(e.id, [])), registros.get(e.id, 0)) for e in establecimientos]
        if lotes.get(None) or registros.get(None):
            campos.append(Campo(None, _ordenar_lotes(lotes.get(None, [])), registros.get(None, 0)))
        return campos

    # --- Borrado grande esperando confirmación ---------------------------------

    def guardar_borrado_pendiente(self, ids: list[int], creado: datetime) -> None:
        self.db.merge(BorradoPendiente(usuario_id=self.usuario_id, ids=ids, creado=creado))

    def tomar_borrado_pendiente(self) -> BorradoPendiente | None:
        """El borrado pendiente, si hay uno. Se descarta al tomarlo: se usa una sola vez."""
        pendiente = self.db.get(BorradoPendiente, self.usuario_id)
        if pendiente is not None:
            self.db.delete(pendiente)
            self.db.flush()
        return pendiente

    # --- Charla reciente con el bot -------------------------------------------

    def charla(self, desde: datetime, limite: int) -> list[MensajeChat]:
        """Los últimos mensajes desde esa hora, del más viejo al más nuevo."""
        q = (
            select(MensajeChat)
            .where(MensajeChat.usuario_id == self.usuario_id, MensajeChat.creado >= desde)
            .order_by(MensajeChat.id.desc())
            .limit(limite)
        )
        return list(reversed(self.db.scalars(q).all()))

    def guardar_charla(self, mensajes: list[tuple[str, str]], conservar: int) -> None:
        """Guarda (rol, texto) y borra los más viejos, para no guardar más de `conservar`."""
        for rol, texto in mensajes:
            self.db.add(MensajeChat(usuario_id=self.usuario_id, rol=rol, texto=texto))
        viejos = self.db.scalars(
            select(MensajeChat.id)
            .where(MensajeChat.usuario_id == self.usuario_id)
            .order_by(MensajeChat.id.desc())
            .offset(conservar)
        ).all()
        if viejos:
            self.db.execute(delete(MensajeChat).where(MensajeChat.id.in_(viejos)))
        self.db.flush()

    # --- Cupo diario de uso de la IA -------------------------------------------

    def consumir_cupo(self, hoy: date, limite: int) -> bool:
        """Suma un uso del día. False si ya llegó al límite (y entonces no suma)."""
        uso = self.db.scalar(select(UsoDiario).where(UsoDiario.usuario_id == self.usuario_id, UsoDiario.fecha == hoy))
        if uso is None:
            uso = UsoDiario(usuario_id=self.usuario_id, fecha=hoy, cantidad=0)
            self.db.add(uso)
        if uso.cantidad >= limite:
            return False
        uso.cantidad += 1
        self.db.flush()
        return True

    # --- Todo ------------------------------------------------------------------

    def borrar_todo(self) -> None:
        """Elimina todo lo que se guardó de esta persona y de su cuenta (derecho de supresión).

        Hoy cada persona tiene su propia cuenta, así que se borra todo lo de la cuenta."""
        self.db.execute(delete(Evento).where(Evento.cuenta_id == self.cuenta_id))
        self.db.execute(
            update(Usuario).where(Usuario.cuenta_id == self.cuenta_id).values(establecimiento_actual_id=None)
        )
        self.db.execute(delete(Lote).where(Lote.cuenta_id == self.cuenta_id))
        self.db.execute(delete(Establecimiento).where(Establecimiento.cuenta_id == self.cuenta_id))
        for modelo in (MensajeChat, UsoDiario, BorradoPendiente, Solicitud):
            self.db.execute(delete(modelo).where(modelo.usuario_id == self.usuario_id))
        self.db.flush()


def _ordenar_lotes(nombres: list[str]) -> list[str]:
    """Los números en orden de número (2, 10) y después los nombres (potrero grande)."""
    return sorted(nombres, key=lambda n: (0, int(n), "") if n.isdecimal() else (1, 0, n))
