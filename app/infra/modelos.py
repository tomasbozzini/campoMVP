from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base


def _ahora() -> datetime:
    return datetime.now(UTC)


class Cuenta(Base):
    """La dueña de los datos: los registros (y todo lo que se anota) son de una cuenta.

    Hoy cada persona tiene la suya; más adelante, un estudio con varios profesionales
    compartirá una cuenta sin que cambie cómo se guardan los datos.
    """

    __tablename__ = "cuentas"

    id: Mapped[int] = mapped_column(primary_key=True)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Usuario(Base):
    """Un número de WhatsApp. Cada persona tiene su propio cuaderno privado de registros."""

    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id"), index=True)
    telefono: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    nombre: Mapped[str | None] = mapped_column(String(120))  # nombre de perfil de WhatsApp
    # Perfil, completado con preguntas fijas (app/nucleo/perfil.py). El rubro define los módulos.
    nombre_completo: Mapped[str | None] = mapped_column(String(80))
    rubro: Mapped[str | None] = mapped_column(String(20))  # veterinario | agronomo | productor
    localidad: Mapped[str | None] = mapped_column(String(80))
    matricula: Mapped[str | None] = mapped_column(String(30))  # opcional, va en el membrete del PDF
    # Pregunta fija que espera respuesta (alta o cambio de un dato del perfil).
    pregunta: Mapped[str | None] = mapped_column(String(20))
    # Solo los números autorizados por un administrador pueden usar el bot.
    autorizado: Mapped[bool] = mapped_column(Boolean, default=False)
    # Último establecimiento que nombró: se usa cuando anota algo sin decir dónde fue.
    establecimiento_actual_id: Mapped[int | None] = mapped_column(ForeignKey("establecimientos.id"))
    # Solo el administrador: guarda sus mensajes para el set de evaluación (paso 9a, `Prueba`).
    modo_prueba: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)

    establecimiento_actual: Mapped["Establecimiento | None"] = relationship(lazy="joined")


class Establecimiento(Base):
    """Un campo donde trabaja la persona ("La Esperanza"). Es de la cuenta: otra persona que
    trabaja en el mismo campo tiene el suyo, con sus propios registros."""

    __tablename__ = "establecimientos"
    __table_args__ = (UniqueConstraint("cuenta_id", "clave"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(120))  # como lo escribió la primera vez
    # Para reconocerlo escrito de otra forma: "Estancia La Esperanza" y "la esperanza" son el mismo.
    clave: Mapped[str] = mapped_column(String(120))
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Lote(Base):
    """Un lote o potrero de un establecimiento. Si se nombró sin decir el campo, queda suelto
    (sin establecimiento): "el lote 3" de La Esperanza y el suelto son lotes distintos."""

    __tablename__ = "lotes"
    __table_args__ = (UniqueConstraint("cuenta_id", "establecimiento_id", "nombre"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id"), index=True)
    establecimiento_id: Mapped[int | None] = mapped_column(ForeignKey("establecimientos.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(60))  # sin la palabra "lote": "3", "potrero grande"
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Sesion(Base):
    """Un trabajo en un lote, una manga o una tarea ("manga en El Retiro", "siembra lote Los
    Pinos"): lo que se anota sin decir el campo mientras está abierta queda en ella. Una
    abierta por persona."""

    __tablename__ = "sesiones"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)  # quién la abrió
    establecimiento_id: Mapped[int | None] = mapped_column(ForeignKey("establecimientos.id"))
    lote_id: Mapped[int | None] = mapped_column(ForeignKey("lotes.id"))
    actividad: Mapped[str | None] = mapped_column(String(60))  # "manga", "siembra", "tacto vaquillonas"
    abierta: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ultima_actividad: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # último mensaje de la persona
    cerrada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)  # None: abierta
    motivo_cierre: Mapped[str | None] = mapped_column(String(10))  # pedido | otra | tiempo

    establecimiento: Mapped[Establecimiento | None] = relationship(lazy="joined")
    lote: Mapped[Lote | None] = relationship(lazy="joined")


class Animal(Base):
    """Un animal identificado por su RP, su caravana o los dos (un toro que se raspa), para
    seguirlo de un registro a otro (1.° y 2.° raspaje). Es de un campo de la cuenta, como los
    lotes: el toro 405 de La Pastora y el de El Retiro son dos animales; sin campo, queda suelto."""

    __tablename__ = "animales"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id"), index=True)
    establecimiento_id: Mapped[int | None] = mapped_column(ForeignKey("establecimientos.id"), index=True)
    rp: Mapped[str | None] = mapped_column(String(40))  # como lo dijo, sin "RP"
    caravana: Mapped[str | None] = mapped_column(String(40))
    categoria: Mapped[str | None] = mapped_column(String(40))  # "toro"
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)

    establecimiento: Mapped[Establecimiento | None] = relationship(lazy="joined")

    @property
    def nombre(self) -> str:
        """ "RP 412", "405" o "RP 412 · caravana 405"."""
        if self.rp and self.caravana:
            return f"RP {self.rp} · caravana {self.caravana}"
        return f"RP {self.rp}" if self.rp else self.caravana or "?"


class Evento(Base):
    """Cualquier cosa que anotó una persona: sanidad, movimientos, pesadas, clima, etc.

    Pertenece SOLO a la cuenta de quien lo anotó. Nadie más lo ve, aunque sea del mismo
    establecimiento.
    """

    __tablename__ = "eventos"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)  # quién lo anotó
    # Dónde pasó. El establecimiento y los lotes son de la misma cuenta que el registro.
    establecimiento_id: Mapped[int | None] = mapped_column(ForeignKey("establecimientos.id"), index=True)
    lote_id: Mapped[int | None] = mapped_column(ForeignKey("lotes.id"), index=True)  # lote o potrero / de origen
    lote_destino_id: Mapped[int | None] = mapped_column(ForeignKey("lotes.id"), index=True)  # traslados: a dónde
    # La sesión en la que se anotó; None si no había una abierta o si fue en otro campo.
    sesion_id: Mapped[int | None] = mapped_column(ForeignKey("sesiones.id"), index=True)
    # Un mensaje puede traer varios eventos; comparten este id para que "borrar"
    # los deshaga juntos y no toque los del mensaje anterior.
    mensaje_id: Mapped[str | None] = mapped_column(String(36), index=True)

    # sanidad | movimiento | pesada | reproduccion | campo
    categoria: Mapped[str] = mapped_column(String(20), index=True)
    # ej: vacunacion, desparasitacion, tratamiento, nacimiento, muerte, compra, venta,
    # traslado, pesaje, tacto, servicio, destete, lluvia, siembra, fumigacion, ...
    tipo: Mapped[str] = mapped_column(String(30), index=True)

    descripcion: Mapped[str | None] = mapped_column(Text)
    producto: Mapped[str | None] = mapped_column(String(120))  # vacuna, droga, semilla...
    dosis: Mapped[str | None] = mapped_column(String(60))
    cantidad_animales: Mapped[int | None] = mapped_column(Integer)
    categoria_animal: Mapped[str | None] = mapped_column(String(40))  # vacas, terneros, novillos...
    caravana: Mapped[str | None] = mapped_column(String(40), index=True)
    # El animal identificado del registro (un raspaje); None en los demás.
    animal_id: Mapped[int | None] = mapped_column(ForeignKey("animales.id"), index=True)
    valor: Mapped[float | None] = mapped_column(Float)  # kg, mm de lluvia, hectáreas, $...
    unidad: Mapped[str | None] = mapped_column(String(20))

    fecha_evento: Mapped[date] = mapped_column(Date, index=True)
    confianza: Mapped[str | None] = mapped_column(String(10))
    mensaje_original: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)

    # Se cargan con el registro: se muestran siempre que se muestra un registro.
    establecimiento: Mapped[Establecimiento | None] = relationship(lazy="joined")
    lote: Mapped[Lote | None] = relationship(foreign_keys=[lote_id], lazy="joined")
    lote_destino: Mapped[Lote | None] = relationship(foreign_keys=[lote_destino_id], lazy="joined")
    animal: Mapped[Animal | None] = relationship(lazy="joined")

    @property
    def nombre_establecimiento(self) -> str | None:
        return self.establecimiento.nombre if self.establecimiento else None

    @property
    def nombre_lote(self) -> str | None:
        return self.lote.nombre if self.lote else None

    @property
    def nombre_lote_destino(self) -> str | None:
        return self.lote_destino.nombre if self.lote_destino else None


class Pendiente(Base):
    """Algo que la persona tiene que hacer más adelante ("revisar las vaquillonas el martes").
    Es de la cuenta, como los registros. Hecho se guarda con su fecha y sale de la lista."""

    __tablename__ = "pendientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)  # quién lo anotó
    establecimiento_id: Mapped[int | None] = mapped_column(ForeignKey("establecimientos.id"))
    lote_id: Mapped[int | None] = mapped_column(ForeignKey("lotes.id"))
    texto: Mapped[str] = mapped_column(String(200))  # qué hay que hacer, con las palabras de la persona
    vence: Mapped[date | None] = mapped_column(Date)  # para cuándo, si lo dijo
    hecho: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)  # None: pendiente
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)

    establecimiento: Mapped[Establecimiento | None] = relationship(lazy="joined")
    lote: Mapped[Lote | None] = relationship(lazy="joined")


class MensajeProcesado(Base):
    """Meta reintenta los webhooks: guardamos el id para no procesar dos veces."""

    __tablename__ = "mensajes_procesados"

    wamid: Mapped[str] = mapped_column(String(128), primary_key=True)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Cotizacion(Base):
    """Un precio de referencia publicado por una fuente oficial o un mercado regulado.

    Solo lo carga app/fuentes/precios.py desde las fuentes registradas: el modelo de lenguaje
    nunca escribe ni inventa precios.
    """

    __tablename__ = "cotizaciones"
    __table_args__ = (UniqueConstraint("fuente", "producto", "plaza", "fecha"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rubro: Mapped[str] = mapped_column(String(20), index=True)  # granos | hacienda | ...
    producto: Mapped[str] = mapped_column(String(40), index=True)  # soja, maiz, novillo...
    plaza: Mapped[str | None] = mapped_column(String(60))  # Rosario, Cañuelas...
    valor: Mapped[float] = mapped_column(Float)
    moneda: Mapped[str] = mapped_column(String(3), default="ARS")  # ARS | USD, tal como publica la fuente
    unidad: Mapped[str] = mapped_column(String(20))  # "t", "kg vivo"
    fecha: Mapped[date] = mapped_column(Date, index=True)  # fecha de publicación que informa la fuente
    # Si el precio incluye impuestos (IVA). None = la fuente no lo informa.
    incluye_impuestos: Mapped[bool | None] = mapped_column(Boolean)
    # Costos adicionales que aclara la fuente: "No incluye comisión ni flete", etc.
    costos_adicionales: Mapped[str | None] = mapped_column(String(300))
    fuente: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(300))
    obtenido: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class UsoDiario(Base):
    """Cuántas veces por día cada usuario usó la IA, para cortar abusos."""

    __tablename__ = "uso_diario"
    __table_args__ = (UniqueConstraint("usuario_id", "fecha"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    fecha: Mapped[date] = mapped_column(Date)
    cantidad: Mapped[int] = mapped_column(Integer, default=0)


class ProductoVeterinario(Base):
    """Un producto del registro oficial de SENASA (Vademécum de Productos Veterinarios).

    Sirve solo para verificar si un producto está aprobado para comercializarse. No se
    guardan precios ni indicaciones de uso.
    """

    __tablename__ = "productos_veterinarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200), index=True)  # nombre comercial
    nombre_busqueda: Mapped[str] = mapped_column(String(200), index=True)  # minúscula y sin tildes
    registro: Mapped[str] = mapped_column(String(40))  # número de registro SENASA
    titular: Mapped[str | None] = mapped_column(String(200))  # laboratorio / empresa titular
    principio_activo: Mapped[str | None] = mapped_column(String(300))
    principio_busqueda: Mapped[str | None] = mapped_column(String(300))
    estado: Mapped[str | None] = mapped_column(String(40))  # vigente, vencido, suspendido... (como lo publica SENASA)
    fecha_datos: Mapped[date] = mapped_column(Date)  # fecha de los datos según la fuente
    fuente: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(300))
    obtenido: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class MensajeChat(Base):
    """Últimos mensajes de cada persona con el bot, para que la IA entienda el contexto
    ("sí", "esa", "la de ayer", la respuesta a una pregunta del bot).

    Solo se usan los de la misma persona y de los últimos minutos (ver app/nucleo/charla.py).
    """

    __tablename__ = "mensajes_chat"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    rol: Mapped[str] = mapped_column(String(10))  # "usuario" | "bot"
    texto: Mapped[str] = mapped_column(Text)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, index=True)


class BorradoPendiente(Base):
    """Una pregunta esperando que la persona confirme con "sí": un borrado grande (el nombre
    viene de ahí), una corrección de muchos pendientes o un campo parecido a otro.

    Se guardan los ids y, si hace falta, los datos para terminar el pedido; se descarta si la
    persona manda otra cosa o pasa el tiempo.
    """

    __tablename__ = "borrados_pendientes"

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    # registros | pendientes (borrar) | corregir (pendientes) | campo (¿es el mismo campo?)
    que: Mapped[str] = mapped_column(String(10), default="registros", server_default="registros")
    ids: Mapped[list[int]] = mapped_column(JSON)
    datos: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Prueba(Base):
    """Un mensaje del administrador en modo prueba (paso 9a): lo que vio la IA, el JSON que
    devolvió y lo que respondió el bot, para armar el set de evaluación (`eval revisar`). De un
    audio se guarda solo la transcripción."""

    __tablename__ = "pruebas"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    texto: Mapped[str] = mapped_column(Text)  # el mensaje o la transcripción del audio
    audio: Mapped[bool] = mapped_column(Boolean, default=False)
    historial: Mapped[list[list[str]]] = mapped_column(JSON)  # la charla que vio la IA: [rol, texto]
    pregunta: Mapped[str | None] = mapped_column(String(20))  # la pregunta abierta (`nucleo/preguntas.py`)
    hoy: Mapped[date] = mapped_column(Date)
    interpretacion: Mapped[Any] = mapped_column(JSON, nullable=False)  # lo que devolvió la IA, tal cual
    respuesta: Mapped[str] = mapped_column(Text)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Invitacion(Base):
    """Un código para darse de alta. Sirve para una sola persona y vence a los 7 días."""

    __tablename__ = "invitaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    # ANOTA-XXXX-XXXX (o CAMPO-XXXX-XXXX, los de antes del paso 8.6)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
    vence: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Id del administrador que la creó. Sin clave foránea, como en la auditoría.
    creada_por: Mapped[int | None] = mapped_column(Integer)
    usada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anulada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Solicitud(Base):
    """Un pedido de alta. Con código de invitación se aprueba solo al completar las preguntas;
    preparado para sumar después la aprobación del administrador (origen "pedido")."""

    __tablename__ = "solicitudes"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    invitacion_id: Mapped[int | None] = mapped_column(ForeignKey("invitaciones.id"))
    origen: Mapped[str] = mapped_column(String(10))  # codigo | pedido | admin
    estado: Mapped[str] = mapped_column(String(10), index=True)  # pendiente | aprobada | rechazada
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
    resuelto: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntentoAlta(Base):
    """Códigos equivocados por número, para limitar los intentos.

    El teléfono se guarda con HMAC (CLAVE_HASH): de quien no se dio de alta no se guarda
    nada personal. Se borra a las 24 horas.
    """

    __tablename__ = "intentos_alta"

    telefono_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    desde: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cantidad: Mapped[int] = mapped_column(Integer, default=0)


class Auditoria(Base):
    """Acciones sensibles: altas y bajas, invitaciones, borrados.

    Solo ids numéricos y cantidades: nunca teléfonos, nombres ni textos. Las filas se
    conservan después de "borrar mis datos"; por eso `actor` y `sobre` no son claves
    foráneas ni se llaman `usuario_id` (el id queda, la persona ya no existe).
    """

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, index=True)
    accion: Mapped[str] = mapped_column(String(30))
    actor: Mapped[int | None] = mapped_column(Integer)  # usuario que la hizo; None = desde la terminal
    sobre: Mapped[int | None] = mapped_column(Integer)  # usuario afectado
    detalle: Mapped[dict[str, int] | None] = mapped_column(JSON)  # cantidades e ids
