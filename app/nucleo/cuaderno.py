"""Acceso a los datos de UNA persona: su cuaderno, su charla con el bot, su cupo diario y
los borrados que esperan confirmación.

Es la única puerta a esas tablas. Cada consulta queda filtrada por el usuario con el que
se abrió el cuaderno, así que no hay forma de leer ni tocar lo de otra persona aunque un
id venga mal. Fuera de este módulo nadie filtra por `usuario_id` a mano.
"""

from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.infra.modelos import BorradoPendiente, Evento, MensajeChat, UsoDiario
from app.nucleo.normalizar import normalizar_lote

# Tope de registros que devuelve una búsqueda.
MAX_EVENTOS = 5000


def _fecha(valor: object) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        return None


class Cuaderno:
    def __init__(self, db: Session, usuario_id: int) -> None:
        self.db = db
        self.usuario_id = usuario_id

    # --- Registros ------------------------------------------------------------

    def agregar(self, eventos: list[Evento]) -> None:
        for evento in eventos:
            evento.usuario_id = self.usuario_id
            self.db.add(evento)
        self.db.flush()

    def recientes(self, limite: int) -> list[Evento]:
        """Los últimos registros anotados, del más nuevo al más viejo."""
        q = select(Evento).where(Evento.usuario_id == self.usuario_id).order_by(Evento.id.desc()).limit(limite)
        return list(self.db.scalars(q).all())

    def ultimo(self) -> Evento | None:
        return next(iter(self.recientes(1)), None)

    def del_mensaje(self, mensaje_id: str) -> list[Evento]:
        """Los registros que se anotaron juntos, con un mismo mensaje."""
        q = select(Evento).where(Evento.usuario_id == self.usuario_id, Evento.mensaje_id == mensaje_id)
        return list(self.db.scalars(q).all())

    def cantidad(self) -> int:
        return self.db.scalar(select(func.count(Evento.id)).where(Evento.usuario_id == self.usuario_id)) or 0

    def borrar(self, ids: list[int]) -> int:
        """Borra esos registros, solo si son de esta persona. Devuelve cuántos borró."""
        resultado = self.db.execute(delete(Evento).where(Evento.id.in_(ids), Evento.usuario_id == self.usuario_id))
        return int(getattr(resultado, "rowcount", 0) or 0)

    def buscar(self, filtros: dict) -> list[Evento]:
        """Busca con los filtros que arma el modelo. El modelo nunca escribe SQL ni ve los
        resultados: solo devuelve filtros. `establecimiento` ya viene normalizado
        (normalizar.clave_establecimiento)."""
        q = select(Evento).where(Evento.usuario_id == self.usuario_id)
        if filtros.get("establecimiento"):
            q = q.where(Evento.establecimiento_clave == filtros["establecimiento"])
        if filtros.get("categoria"):
            q = q.where(Evento.categoria == str(filtros["categoria"]).lower())
        if filtros.get("tipo"):
            q = q.where(Evento.tipo == str(filtros["tipo"]).lower())
        if lote := normalizar_lote(filtros.get("lote")):
            q = q.where((Evento.lote == lote) | (Evento.lote_destino == lote))
        if filtros.get("caravana"):
            q = q.where(func.lower(Evento.caravana) == str(filtros["caravana"]).lower())
        if filtros.get("categoria_animal"):
            raiz = str(filtros["categoria_animal"]).lower().rstrip("s")
            q = q.where(func.lower(Evento.categoria_animal).like(f"%{raiz}%"))
        if filtros.get("producto"):
            texto = f"%{str(filtros['producto']).lower()}%"
            q = q.where(func.lower(Evento.producto).like(texto) | func.lower(Evento.descripcion).like(texto))
        if desde := _fecha(filtros.get("desde")):
            q = q.where(Evento.fecha_evento >= desde)
        if hasta := _fecha(filtros.get("hasta")):
            q = q.where(Evento.fecha_evento <= hasta)
        q = q.order_by(Evento.fecha_evento.desc(), Evento.id.desc()).limit(MAX_EVENTOS)
        return list(self.db.scalars(q).all())

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
        """Elimina todo lo que se guardó de esta persona (derecho de supresión)."""
        for modelo in (Evento, MensajeChat, UsoDiario, BorradoPendiente):
            self.db.execute(delete(modelo).where(modelo.usuario_id == self.usuario_id))
        self.db.flush()
