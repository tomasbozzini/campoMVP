"""Acceso a los datos de UNA persona: el cuaderno de su cuenta (registros, establecimientos,
lotes, sesiones y pendientes), su charla con el bot, su cupo diario y los borrados que esperan confirmación.

Es la única puerta a esas tablas. Lo que se anota es de la cuenta y se filtra por la cuenta
de quien abrió el cuaderno (hoy, 1 persona = 1 cuenta); la charla, el cupo y los borrados
pendientes son de la conversación de cada persona y se filtran por usuario. No hay forma de
leer ni tocar lo de otra cuenta aunque un id venga mal. Fuera de este módulo nadie filtra
por `cuenta_id` ni por `usuario_id` a mano.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.infra.modelos import (
    BorradoPendiente,
    Establecimiento,
    Evento,
    Lote,
    MensajeChat,
    Pendiente,
    Sesion,
    Solicitud,
    UsoDiario,
    Usuario,
)
from app.infra.texto import prolijo
from app.nucleo import auditoria
from app.nucleo.normalizar import PARECIDO_MINIMO, clave_establecimiento, normalizar_lote, parecido

# Tope de registros que devuelve una búsqueda.
MAX_EVENTOS = 5000


@dataclass(frozen=True)
class Campo:
    """Un establecimiento con sus lotes y cuántos registros tiene. Sin establecimiento: los
    lotes sueltos y los registros que no dicen dónde fueron."""

    establecimiento: Establecimiento | None
    lotes: list[str]
    registros: int
    pendientes: int = 0  # los que no están hechos


@dataclass(frozen=True)
class Contenido:
    """Lo que tiene un campo o un lote: lo que pasa al otro si se unen."""

    registros: int
    pendientes: int  # hechos o no
    sesiones: int
    lotes: list[str]  # solo los de un campo: sus lotes
    lotes_iguales: list[str]  # de esos, los que el otro campo ya tiene con el mismo nombre


class CampoParecido(Exception):
    """El nombre de un campo nuevo se parece mucho al de uno que ya existe ("Omu" y "El
    Ombú"): antes de crearlo se le pregunta a la persona si es el mismo."""

    def __init__(self, nombre: str, existente: Establecimiento) -> None:
        super().__init__(nombre)
        self.nombre = nombre
        self.existente = existente


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
        # Lo que la persona ya respondió sobre campos parecidos en este pedido: qué nombre es
        # un campo que ya existe (clave -> id) y cuáles son campos nuevos aunque se parezcan.
        self.alias: dict[str, int] = {}
        self.permitidos: set[str] = set()
        # Y sobre fechas dudosas ("el viernes 22" cuando el 22 es jueves): qué fecha eligió.
        self.fechas: dict[str, str] = {}

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
        esperanza"). Si es la primera vez que lo nombra, se crea con el nombre como lo escribió,
        prolijo ("estancia LA PASTORA" -> "Estancia la Pastora").

        Si el nombre nuevo se parece mucho a uno que ya tiene ("Omu" y "El Ombú"), no se crea:
        se levanta `CampoParecido` para preguntarle si es el mismo (salvo que ya lo haya
        respondido: `alias` y `permitidos`)."""
        clave = clave_establecimiento(nombre)
        if not nombre or not clave:
            return None
        existente = self.db.scalar(
            select(Establecimiento).where(Establecimiento.cuenta_id == self.cuenta_id, Establecimiento.clave == clave)
        )
        if existente is not None:
            return existente
        if clave in self.alias:
            elegido = self.db.get(Establecimiento, self.alias[clave])
            if elegido is not None and elegido.cuenta_id == self.cuenta_id:
                return elegido
        if clave not in self.permitidos and (parecido_a := self._parecido(clave)) is not None:
            raise CampoParecido(prolijo(nombre), parecido_a)
        nuevo = Establecimiento(cuenta_id=self.cuenta_id, nombre=prolijo(nombre), clave=clave)
        self.db.add(nuevo)
        self.db.flush()
        return nuevo

    def establecimiento_existente(self, nombre: str | None) -> Establecimiento | None:
        """El establecimiento con ese nombre, escrito como sea; None si no lo tiene (no lo crea
        ni busca uno parecido)."""
        clave = clave_establecimiento(nombre)
        if not clave:
            return None
        return self.db.scalar(
            select(Establecimiento).where(Establecimiento.cuenta_id == self.cuenta_id, Establecimiento.clave == clave)
        )

    def renombrar_establecimiento(self, establecimiento: Establecimiento, nombre: str) -> None:
        """Le cambia el nombre (y la clave). Ningún otro de la cuenta puede tener esa clave."""
        if establecimiento.cuenta_id != self.cuenta_id:
            raise ValueError("El establecimiento es de otra cuenta")
        establecimiento.nombre = prolijo(nombre)
        establecimiento.clave = clave_establecimiento(nombre) or establecimiento.clave
        self.db.flush()
        auditoria.registrar(
            self.db, auditoria.RENOMBRAR_CAMPO, actor=self.usuario_id, cuenta=self.cuenta_id, campo=establecimiento.id
        )

    def contenido_establecimiento(self, origen: Establecimiento, destino: Establecimiento) -> Contenido:
        """Lo que pasaría de `origen` a `destino` si se unen."""
        lotes = self._lotes_de(origen.id)
        del_destino = {lote.nombre for lote in self._lotes_de(destino.id)}
        return Contenido(
            registros=self._contar(Evento, Evento.establecimiento_id == origen.id),
            pendientes=self._contar(Pendiente, Pendiente.establecimiento_id == origen.id),
            sesiones=self._contar(Sesion, Sesion.establecimiento_id == origen.id),
            lotes=_ordenar_lotes([lote.nombre for lote in lotes]),
            lotes_iguales=_ordenar_lotes([lote.nombre for lote in lotes if lote.nombre in del_destino]),
        )

    def unir_establecimientos(self, origen_id: int, destino_id: int) -> Contenido | None:
        """Pasa todo lo de `origen` a `destino` y borra `origen`: registros, pendientes, sesiones
        y lotes (los que `destino` ya tiene con el mismo nombre se unen). Quien tenía `origen`
        como campo actual pasa a tener `destino`. None si alguno ya no está."""
        origen = self.db.get(Establecimiento, origen_id)
        destino = self.db.get(Establecimiento, destino_id)
        if origen is None or destino is None or origen.id == destino.id:
            return None
        if origen.cuenta_id != self.cuenta_id or destino.cuenta_id != self.cuenta_id:
            return None
        contenido = self.contenido_establecimiento(origen, destino)
        de_destino = {lote.nombre: lote for lote in self._lotes_de(destino.id)}
        for lote in self._lotes_de(origen.id):
            if lote.nombre in de_destino:
                self._pasar_lote(lote, de_destino[lote.nombre])
            else:
                lote.establecimiento_id = destino.id
        for modelo in (Evento, Pendiente, Sesion):
            self.db.execute(
                update(modelo)
                .where(modelo.cuenta_id == self.cuenta_id, modelo.establecimiento_id == origen.id)
                .values(establecimiento_id=destino.id)
                .execution_options(synchronize_session="fetch")
            )
        self.db.execute(
            update(Usuario)
            .where(Usuario.cuenta_id == self.cuenta_id, Usuario.establecimiento_actual_id == origen.id)
            .values(establecimiento_actual_id=destino.id)
            .execution_options(synchronize_session="fetch")
        )
        self.db.delete(origen)
        self.db.flush()
        # Lo que ya estaba cargado (el campo actual, los registros) puede apuntar al que se borró.
        self.db.expire_all()
        auditoria.registrar(
            self.db,
            auditoria.UNIR_CAMPOS,
            actor=self.usuario_id,
            cuenta=self.cuenta_id,
            origen=origen_id,
            destino=destino_id,
            registros=contenido.registros,
        )
        return contenido

    def lote_existente(self, nombre: str | None, establecimiento: Establecimiento | None) -> Lote | None:
        """El lote con ese nombre en ese campo (o suelto); None si no lo tiene (no lo crea)."""
        limpio = normalizar_lote(nombre)
        lotes = self._lotes_de(establecimiento.id if establecimiento else None)
        return next((lote for lote in lotes if lote.nombre == limpio), None) if limpio else None

    def renombrar_lote(self, lote: Lote, nombre: str) -> None:
        """Le cambia el nombre. Ningún otro lote de su campo puede llamarse así."""
        if lote.cuenta_id != self.cuenta_id:
            raise ValueError("El lote es de otra cuenta")
        lote.nombre = normalizar_lote(nombre) or lote.nombre
        self.db.flush()
        auditoria.registrar(
            self.db, auditoria.RENOMBRAR_LOTE, actor=self.usuario_id, cuenta=self.cuenta_id, lote=lote.id
        )

    def contenido_lote(self, lote: Lote) -> Contenido:
        """Lo que pasaría de ese lote a otro si se unen."""
        return Contenido(
            registros=self._contar(Evento, (Evento.lote_id == lote.id) | (Evento.lote_destino_id == lote.id)),
            pendientes=self._contar(Pendiente, Pendiente.lote_id == lote.id),
            sesiones=self._contar(Sesion, Sesion.lote_id == lote.id),
            lotes=[],
            lotes_iguales=[],
        )

    def unir_lotes(self, origen_id: int, destino_id: int) -> Contenido | None:
        """Pasa todo lo de un lote a otro del mismo campo y borra el primero. None si alguno ya
        no está o no son del mismo campo."""
        origen = self.db.get(Lote, origen_id)
        destino = self.db.get(Lote, destino_id)
        if origen is None or destino is None or origen.id == destino.id:
            return None
        if origen.cuenta_id != self.cuenta_id or destino.cuenta_id != self.cuenta_id:
            return None
        if origen.establecimiento_id != destino.establecimiento_id:
            return None
        contenido = self.contenido_lote(origen)
        self._pasar_lote(origen, destino)
        self.db.flush()
        auditoria.registrar(
            self.db,
            auditoria.UNIR_LOTES,
            actor=self.usuario_id,
            cuenta=self.cuenta_id,
            origen=origen_id,
            destino=destino_id,
            registros=contenido.registros,
        )
        return contenido

    def _pasar_lote(self, origen: Lote, destino: Lote) -> None:
        """Lo que apunta a `origen` pasa a apuntar a `destino`, y `origen` se borra."""
        for modelo, columna in (
            (Evento, "lote_id"),
            (Evento, "lote_destino_id"),
            (Pendiente, "lote_id"),
            (Sesion, "lote_id"),
        ):
            self.db.execute(
                update(modelo)
                .where(modelo.cuenta_id == self.cuenta_id, getattr(modelo, columna) == origen.id)
                .values({columna: destino.id})
                .execution_options(synchronize_session="fetch")
            )
        self.db.delete(origen)
        self.db.flush()
        # Lo que ya estaba cargado (el campo actual, los registros) puede apuntar al que se borró.
        self.db.expire_all()

    def _lotes_de(self, establecimiento_id: int | None) -> list[Lote]:
        campo = (
            Lote.establecimiento_id.is_(None)
            if establecimiento_id is None
            else Lote.establecimiento_id == establecimiento_id
        )
        return list(self.db.scalars(select(Lote).where(Lote.cuenta_id == self.cuenta_id, campo)).all())

    def _contar(self, modelo: type[Evento] | type[Pendiente] | type[Sesion], condicion: Any) -> int:
        q = select(func.count(modelo.id)).where(modelo.cuenta_id == self.cuenta_id, condicion)
        return self.db.scalar(q) or 0

    def _parecido(self, clave: str) -> Establecimiento | None:
        """El establecimiento con el nombre más parecido a esa clave, si pasa el mínimo."""
        candidatos = self.db.scalars(select(Establecimiento).where(Establecimiento.cuenta_id == self.cuenta_id))
        puntaje, mejor = max(
            ((parecido(clave, e.clave), e) for e in candidatos), default=(0.0, None), key=lambda x: x[0]
        )
        return mejor if puntaje >= PARECIDO_MINIMO else None

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
        pendientes: dict[int | None, int] = dict(
            self.db.execute(
                select(Pendiente.establecimiento_id, func.count(Pendiente.id))
                .where(Pendiente.cuenta_id == self.cuenta_id, Pendiente.hecho.is_(None))
                .group_by(Pendiente.establecimiento_id)
            ).all()
        )
        campos = [
            Campo(e, _ordenar_lotes(lotes.get(e.id, [])), registros.get(e.id, 0), pendientes.get(e.id, 0))
            for e in establecimientos
        ]
        if lotes.get(None) or registros.get(None) or pendientes.get(None):
            campos.append(
                Campo(None, _ordenar_lotes(lotes.get(None, [])), registros.get(None, 0), pendientes.get(None, 0))
            )
        return campos

    def nombres_propios(self) -> list[str]:
        """Los nombres de sus campos, del que tiene más registros al que menos, y después los
        de sus lotes que no son números ("potrero grande"): para que Whisper los escriba bien."""
        campos = self.campos()
        por_uso = sorted(campos, key=lambda c: -c.registros)
        nombres = [c.establecimiento.nombre for c in por_uso if c.establecimiento is not None]
        lotes = [lote for c in campos for lote in c.lotes if not lote.isdecimal()]
        return list(dict.fromkeys([*nombres, *lotes]))

    # --- Sesiones -------------------------------------------------------------

    def sesion_abierta(self) -> Sesion | None:
        """La sesión abierta de esta persona (hay una sola, como mucho)."""
        return self.db.scalar(
            select(Sesion)
            .where(Sesion.usuario_id == self.usuario_id, Sesion.cerrada.is_(None))
            .order_by(Sesion.id.desc())
            .limit(1)
        )

    def abrir_sesion(
        self, establecimiento: Establecimiento | None, lote: Lote | None, actividad: str | None, ahora: datetime
    ) -> Sesion:
        for parte in (establecimiento, lote):
            if parte is not None and parte.cuenta_id != self.cuenta_id:
                raise ValueError("El establecimiento o el lote es de otra cuenta")
        sesion = Sesion(
            cuenta_id=self.cuenta_id,
            usuario_id=self.usuario_id,
            establecimiento=establecimiento,
            lote=lote,
            actividad=actividad,
            abierta=ahora,
            ultima_actividad=ahora,
        )
        self.db.add(sesion)
        self.db.flush()
        return sesion

    def registros_de_sesion(self, sesion: Sesion) -> list[Evento]:
        """Los registros de esa sesión, del más viejo al más nuevo."""
        q = (
            select(Evento)
            .where(Evento.cuenta_id == self.cuenta_id, Evento.sesion_id == sesion.id)
            .order_by(Evento.id)
            .limit(MAX_EVENTOS)
        )
        return list(self.db.scalars(q).all())

    # --- Pendientes -----------------------------------------------------------

    def agregar_pendiente(self, pendiente: Pendiente) -> None:
        for parte in (pendiente.establecimiento, pendiente.lote):
            if parte is not None and parte.cuenta_id != self.cuenta_id:
                raise ValueError("El establecimiento o el lote es de otra cuenta")
        pendiente.cuenta_id = self.cuenta_id
        pendiente.usuario_id = self.usuario_id
        self.db.add(pendiente)
        self.db.flush()

    def pendientes(self, establecimiento_clave: str | None = None) -> list[Pendiente]:
        """Los que no están hechos, del más viejo al más nuevo. Con clave, solo los de ese campo."""
        q = select(Pendiente).where(Pendiente.cuenta_id == self.cuenta_id, Pendiente.hecho.is_(None))
        if establecimiento_clave:
            campo = select(Establecimiento.id).where(
                Establecimiento.cuenta_id == self.cuenta_id, Establecimiento.clave == establecimiento_clave
            )
            q = q.where(Pendiente.establecimiento_id.in_(campo))
        return list(self.db.scalars(q.order_by(Pendiente.id).limit(MAX_EVENTOS)).all())

    def ultimo_pendiente(self) -> Pendiente | None:
        """El último pendiente anotado (hecho o no)."""
        q = select(Pendiente).where(Pendiente.cuenta_id == self.cuenta_id).order_by(Pendiente.id.desc()).limit(1)
        return self.db.scalar(q)

    def corregir_pendientes(
        self,
        ids: list[int],
        texto: str | None = None,
        vence: date | None = None,
        establecimiento_id: int | None = None,
        lote: str | None = None,
    ) -> list[Pendiente]:
        """Cambia esos pendientes (los que no están hechos y son de esta cuenta). Lo que viene
        en None no cambia. El lote se busca en el campo que quede: si cambia el campo, el "lote
        3" pasa a ser el lote 3 del campo nuevo."""
        campo = self.db.get(Establecimiento, establecimiento_id) if establecimiento_id else None
        if campo is not None and campo.cuenta_id != self.cuenta_id:
            raise ValueError("El establecimiento es de otra cuenta")
        q = select(Pendiente).where(
            Pendiente.id.in_(ids), Pendiente.cuenta_id == self.cuenta_id, Pendiente.hecho.is_(None)
        )
        pendientes = list(self.db.scalars(q.order_by(Pendiente.id)).all())
        for p in pendientes:
            nombre_lote = lote or (p.lote.nombre if p.lote else None)
            if texto:
                p.texto = texto
            if vence:
                p.vence = vence
            if campo is not None:
                p.establecimiento = campo
            if lote or campo is not None:
                p.lote = self.lote(nombre_lote, p.establecimiento)
        self.db.flush()
        return pendientes

    def marcar_hechos(self, ids: list[int], cuando: datetime) -> None:
        self.db.execute(
            update(Pendiente)
            .where(Pendiente.id.in_(ids), Pendiente.cuenta_id == self.cuenta_id)
            .values(hecho=cuando)
            .execution_options(synchronize_session="fetch")
        )
        self.db.flush()

    def borrar_pendientes(self, ids: list[int]) -> int:
        """Borra esos pendientes, solo si son de esta cuenta. Devuelve cuántos borró."""
        resultado = self.db.execute(
            delete(Pendiente)
            .where(Pendiente.id.in_(ids), Pendiente.cuenta_id == self.cuenta_id)
            .execution_options(synchronize_session="fetch")
        )
        borrados = int(getattr(resultado, "rowcount", 0) or 0)
        if borrados:
            auditoria.registrar(
                self.db, auditoria.BORRAR_PENDIENTES, actor=self.usuario_id, cuenta=self.cuenta_id, cantidad=borrados
            )
        return borrados

    # --- Borrado grande esperando confirmación ---------------------------------

    def guardar_borrado_pendiente(
        self, ids: list[int], creado: datetime, que: str = "registros", datos: dict[str, Any] | None = None
    ) -> None:
        """Una pregunta esperando el *sí* (ver `modulos/comun/confirmar.py`). `que`: "registros"
        o "pendientes" (borrar), "corregir" (pendientes) o "campo"."""
        self.db.merge(BorradoPendiente(usuario_id=self.usuario_id, que=que, ids=ids, datos=datos, creado=creado))

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

    def devolver_cupo(self, hoy: date) -> None:
        """Resta el uso que se sumó para un mensaje que la IA no pudo interpretar."""
        uso = self.db.scalar(select(UsoDiario).where(UsoDiario.usuario_id == self.usuario_id, UsoDiario.fecha == hoy))
        if uso is not None and uso.cantidad > 0:
            uso.cantidad -= 1
            self.db.flush()

    # --- Todo ------------------------------------------------------------------

    def borrar_todo(self) -> None:
        """Elimina todo lo que se guardó de esta persona y de su cuenta (derecho de supresión).

        Hoy cada persona tiene su propia cuenta, así que se borra todo lo de la cuenta."""
        self.db.execute(delete(Evento).where(Evento.cuenta_id == self.cuenta_id))
        self.db.execute(delete(Sesion).where(Sesion.cuenta_id == self.cuenta_id))
        self.db.execute(delete(Pendiente).where(Pendiente.cuenta_id == self.cuenta_id))
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
