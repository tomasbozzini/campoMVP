import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _bool(nombre: str, default: bool = False) -> bool:
    return os.getenv(nombre, str(default)).strip().lower() in ("1", "true", "si", "sí", "yes")


GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Groq da de baja modelos cada tanto: si este deja de existir (404 model_not_found),
# mirá https://console.groq.com/docs/models y poné otro en GROQ_MODELO.
GROQ_MODELO = os.getenv("GROQ_MODELO", "openai/gpt-oss-120b")
GROQ_MODELO_AUDIO = os.getenv("GROQ_MODELO_AUDIO", "whisper-large-v3-turbo")

# WhatsApp Cloud API (Meta)
WA_TOKEN = os.getenv("WA_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v21.0")
# Los números de Argentina llegan como 549XXXXXXXXXX, pero con el número de prueba
# de Meta a veces hay que enviarles a 54XXXXXXXXXX (sin el 9).
WA_AR_QUITAR_9 = _bool("WA_AR_QUITAR_9")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./campo.db")
# Railway/Heroku entregan "postgres://", SQLAlchemy necesita "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

ZONA_HORARIA = ZoneInfo(os.getenv("ZONA_HORARIA", "America/Argentina/Buenos_Aires"))

# Límites para que nadie use el bot como una IA de uso general
MAX_LARGO_MENSAJE = int(os.getenv("MAX_LARGO_MENSAJE", "800"))  # caracteres
MAX_AUDIO_BYTES = int(os.getenv("MAX_AUDIO_BYTES", str(2 * 1024 * 1024)))  # ~3-4 min de audio
LIMITE_DIARIO_IA = int(os.getenv("LIMITE_DIARIO_IA", "80"))  # mensajes con IA por usuario y día
# Un precio más viejo que esto se muestra avisando que no está actualizado
DIAS_PRECIO_VIGENTE = int(os.getenv("DIAS_PRECIO_VIGENTE", "7"))

# Números de WhatsApp de los administradores, separados por coma (ej: 5492494123456).
# Siempre tienen acceso y pueden autorizar a otros con "autorizar <número>".
ADMIN_TELEFONOS = {t.strip() for t in os.getenv("ADMIN_TELEFONOS", "").split(",") if t.strip()}

# Datos para la política de privacidad que se publica en /privacidad
PRIVACIDAD_RESPONSABLE = os.getenv("PRIVACIDAD_RESPONSABLE", "")  # nombre o razón social
PRIVACIDAD_CONTACTO = os.getenv("PRIVACIDAD_CONTACTO", "")  # email para consultas y pedidos
# URL pública de la política (ej: https://tu-bot.up.railway.app/privacidad), para el comando "privacidad"
PRIVACIDAD_URL = os.getenv("PRIVACIDAD_URL", "")
