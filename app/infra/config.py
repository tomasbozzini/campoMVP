"""Configuración del bot, leída de las variables de entorno (y del .env) y validada al arrancar.

Si una variable tiene un valor inválido, el programa no arranca y el error dice cuál es.
Las que son obligatorias en producción se revisan aparte (`faltantes_para_produccion`),
porque los comandos de terminal (precios, SENASA) no necesitan las claves de WhatsApp.
"""

from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Entorno = Literal["desarrollo", "produccion"]
Esfuerzo = Literal["low", "medium", "high"]


class Configuracion(BaseSettings):
    # env_ignore_empty: una variable vacía (como las del .env.example) cuenta como no definida
    # y toma el valor por defecto, en vez de pisarlo con "".
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    # "produccion" exige las claves de Meta y Groq para arrancar el servidor; "desarrollo"
    # permite probar sin firma del webhook (solo si no hay META_APP_SECRET).
    entorno: Entorno = "produccion"

    groq_api_key: str = ""
    # Groq da de baja modelos cada tanto: si este deja de existir (404 model_not_found),
    # mirá https://console.groq.com/docs/models y poné otro en GROQ_MODELO.
    groq_modelo: str = "openai/gpt-oss-120b"
    groq_modelo_audio: str = "whisper-large-v3-turbo"

    # OpenRouter interpreta los mensajes si está la clave; Groq queda de respaldo (y sigue
    # transcribiendo los audios). Sin la clave, todo va por Groq.
    openrouter_api_key: str = ""
    openrouter_modelo: str = "openai/gpt-oss-120b"
    # Cuánto razona el modelo antes de responder: más es más lento y gasta más tokens. Con el
    # set de evaluación, "low" acertó más que "medium" y tardó menos (paso 8.3 del plan).
    openrouter_esfuerzo: Esfuerzo = "low"

    # WhatsApp Cloud API (Meta)
    wa_token: str = ""
    wa_phone_number_id: str = ""
    wa_verify_token: str = ""
    meta_app_secret: str = ""
    graph_api_version: str = "v21.0"
    # Los números de Argentina llegan como 549XXXXXXXXXX, pero con el número de prueba
    # de Meta a veces hay que enviarles a 54XXXXXXXXXX (sin el 9).
    wa_ar_quitar_9: bool = False

    database_url: str = "sqlite:///./campo.db"
    zona_horaria: ZoneInfo = ZoneInfo("America/Argentina/Buenos_Aires")

    # Límites para que nadie use el bot como una IA de uso general
    max_largo_mensaje: int = 800  # caracteres
    max_audio_bytes: int = 2 * 1024 * 1024  # ~3-4 min de audio
    limite_diario_ia: int = 80  # mensajes con IA por usuario y día
    # Un precio más viejo que esto se muestra avisando que no está actualizado
    dias_precio_vigente: int = 7

    # Números de WhatsApp de los administradores, separados por coma (ej: 5492494123456).
    # Siempre tienen acceso y pueden autorizar a otros con "autorizar <número>".
    admin_telefonos: Annotated[set[str], NoDecode] = set()
    # El número del bot, como se ve en WhatsApp (ej: 5492494000000): arma el link de las
    # invitaciones (wa.me/<número>?text=<código>). Sin él, "invitar" da solo el código.
    wa_numero_bot: str = ""
    # Clave para guardar los teléfonos de quienes prueban códigos equivocados sin guardar el
    # número (HMAC). Obligatoria en producción; generala con:
    # python -c "import secrets; print(secrets.token_hex(32))"
    clave_hash: str = ""

    # Datos para la política de privacidad que se publica en /privacidad
    privacidad_responsable: str = ""  # nombre o razón social
    privacidad_contacto: str = ""  # email para consultas y pedidos
    # URL pública de la política (ej: https://tu-bot.up.railway.app/privacidad), para el comando "privacidad"
    privacidad_url: str = ""

    # Railway la pone en cada despliegue: /salud muestra qué commit está corriendo.
    railway_git_commit_sha: str = ""

    @field_validator("entorno", mode="before")
    @classmethod
    def _entorno(cls, valor: object) -> object:
        return str(valor).strip().lower().replace("ó", "o") if isinstance(valor, str) else valor

    @field_validator("openrouter_esfuerzo", mode="before")
    @classmethod
    def _esfuerzo(cls, valor: object) -> object:
        return valor.strip().lower() if isinstance(valor, str) else valor

    @field_validator("wa_ar_quitar_9", mode="before")
    @classmethod
    def _si_no(cls, valor: object) -> object:
        # Además de true/false, se acepta "si" / "sí" como en el resto de la documentación.
        if isinstance(valor, str) and valor.strip().lower() in ("si", "sí"):
            return True
        if isinstance(valor, str) and valor.strip() == "":
            return False
        return valor

    @field_validator("database_url")
    @classmethod
    def _url_postgres(cls, valor: str) -> str:
        # Railway/Heroku entregan "postgres://", SQLAlchemy necesita "postgresql://"
        return "postgresql://" + valor.removeprefix("postgres://") if valor.startswith("postgres://") else valor

    @field_validator("zona_horaria", mode="before")
    @classmethod
    def _zona(cls, valor: object) -> object:
        if not isinstance(valor, str):
            return valor
        try:
            return ZoneInfo(valor.strip())
        except (ZoneInfoNotFoundError, ValueError):
            # ZoneInfoNotFoundError es un KeyError: pydantic no lo convierte en un error de
            # validación y saldría sin decir qué variable está mal.
            raise ValueError(
                f"ZONA_HORARIA: no existe la zona {valor!r}. Usá una de la lista IANA, ej: America/Argentina/Buenos_Aires"
            ) from None

    @field_validator("admin_telefonos", mode="before")
    @classmethod
    def _telefonos(cls, valor: object) -> object:
        if isinstance(valor, str):
            return {t.strip() for t in valor.split(",") if t.strip()}
        return valor

    @property
    def es_produccion(self) -> bool:
        return self.entorno == "produccion"

    def faltantes_para_produccion(self) -> list[str]:
        """Variables sin las cuales el servidor no puede atender WhatsApp en producción."""
        obligatorias = {
            "META_APP_SECRET": self.meta_app_secret,
            "WA_VERIFY_TOKEN": self.wa_verify_token,
            "WA_TOKEN": self.wa_token,
            "WA_PHONE_NUMBER_ID": self.wa_phone_number_id,
            "GROQ_API_KEY": self.groq_api_key,
            "CLAVE_HASH": self.clave_hash,
        }
        return [nombre for nombre, valor in obligatorias.items() if not valor.strip()]


config = Configuracion()
