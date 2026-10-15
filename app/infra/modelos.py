from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

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
    establecimiento_actual: Mapped[str | None] = mapped_column(String(120))
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Evento(Base):
    """Cualquier cosa que anotó una persona: sanidad, movimientos, pesadas, clima, etc.

    Pertenece SOLO a la cuenta de quien lo anotó. Nadie más lo ve, aunque sea del mismo
    establecimiento.
    """

    __tablename__ = "eventos"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)  # quién lo anotó
    # Dónde pasó, como lo escribió la persona ("La Esperanza") y normalizado para buscar.
    establecimiento: Mapped[str | None] = mapped_column(String(120))
    establecimiento_clave: Mapped[str | None] = mapped_column(String(120), index=True)
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
    lote: Mapped[str | None] = mapped_column(String(60), index=True)
    lote_destino: Mapped[str | None] = mapped_column(String(60))
    valor: Mapped[float | None] = mapped_column(Float)  # kg, mm de lluvia, hectáreas, $...
    unidad: Mapped[str | None] = mapped_column(String(20))

    fecha_evento: Mapped[date] = mapped_column(Date, index=True)
    confianza: Mapped[str | None] = mapped_column(String(10))
    mensaje_original: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


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
    """Un borrado grande esperando que la persona confirme con "sí".

    Se guardan los ids a borrar; se descarta si la persona manda otra cosa o pasa el tiempo.
    """

    __tablename__ = "borrados_pendientes"

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    ids: Mapped[list[int]] = mapped_column(JSON)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Invitacion(Base):
    """Un código para darse de alta. Sirve para una sola persona y vence a los 7 días."""

    __tablename__ = "invitaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)  # CAMPO-XXXX-XXXX
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
