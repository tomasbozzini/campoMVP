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
