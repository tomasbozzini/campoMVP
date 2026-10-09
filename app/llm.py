"""Todo lo que habla con el modelo de lenguaje (Groq)."""

import json
import logging
from datetime import date

from groq import Groq

from app import config

log = logging.getLogger(__name__)

_cliente: Groq | None = None


def _groq() -> Groq:
    global _cliente
    if _cliente is None:
        _cliente = Groq(api_key=config.GROQ_API_KEY)
    return _cliente


PROMPT_INTERPRETAR = """Sos el asistente de WhatsApp de un establecimiento agropecuario argentino.
Recibís mensajes de productores, encargados y peones. Tu tarea es decidir si el mensaje
REGISTRA algo que pasó en el campo, CONSULTA datos ya registrados, o es CHARLA.

La fecha de hoy es {hoy} ({dia_semana}).

Devolvé ÚNICAMENTE un objeto JSON con esta estructura:

{{
  "intencion": "registrar" | "consultar" | "charla",
  "eventos": [ EVENTO, ... ],      // solo si intencion = "registrar"; un mensaje puede traer varios eventos
  "consulta": CONSULTA | null,     // solo si intencion = "consultar"
  "respuesta": string | null       // solo si intencion = "charla": respuesta breve y amable
}}

EVENTO:
{{
  "categoria": "sanidad" | "movimiento" | "pesada" | "reproduccion" | "campo",
  "tipo": string,               // ver lista abajo
  "descripcion": string | null, // resumen corto en castellano
  "producto": string | null,    // vacuna, droga, antiparasitario, semilla, herbicida (ej: "aftosa", "ivermectina")
  "dosis": string | null,       // SOLO dosis del producto (ej: "2 ml"). NUNCA la cantidad de animales
  "cantidad_animales": int | null,
  "categoria_animal": string | null,  // en plural y minúscula: "vacas", "terneros", "vaquillonas", "novillos", "toros"...
  "caravana": string | null,    // identificador de un animal individual (ej: "vaca 213" -> "213")
  "lote": string | null,        // lote o potrero donde ocurrió / de origen. Solo el identificador en minúscula, sin la palabra "lote" (ej: "lote 3" -> "3", "potrero grande" -> "potrero grande")
  "lote_destino": string | null,// solo para traslados: a dónde fueron
  "valor": number | null,       // número asociado: kg de una pesada, mm de lluvia, hectáreas, precio
  "unidad": string | null,      // "kg", "mm", "ha", "$"...
  "fecha_evento": "YYYY-MM-DD" | null,
  "confianza": "alta" | "media" | "baja"
}}

Tipos por categoría:
- sanidad: vacunacion, desparasitacion, tratamiento, otro
- movimiento: nacimiento, muerte, compra, venta, traslado, otro
- pesada: pesaje
- reproduccion: servicio, tacto, paricion, destete, inseminacion, otro
- campo: lluvia, siembra, cosecha, fumigacion, fertilizacion, mantenimiento, otro

CONSULTA (filtros para buscar en la base; poné null en lo que no se pida):
{{
  "categoria": string | null,
  "tipo": string | null,
  "lote": string | null,
  "caravana": string | null,
  "categoria_animal": string | null,
  "producto": string | null,
  "desde": "YYYY-MM-DD" | null,
  "hasta": "YYYY-MM-DD" | null
}}

Reglas:
- Fechas relativas ("ayer", "el lunes", "la semana pasada") convertilas a YYYY-MM-DD usando la fecha de hoy.
  Si no se menciona fecha en un registro, usá la de hoy.
- En consultas como "este mes" o "este año", completá "desde" y "hasta".
- NUNCA inventes datos. Si falta algo, null. Si el mensaje es ambiguo, confianza "baja".
- Las preguntas ("¿cuántas...?", "¿cuándo...?", "¿qué se le dio...?") son "consultar", no "registrar".
"""

PROMPT_RESPONDER = """Sos el asistente de WhatsApp de un campo. Respondé la pregunta del usuario
usando SOLO los datos que te paso (registros de la base de datos del campo). Hoy es {hoy}.

- Respondé corto, claro y en castellano rioplatense, como un mensaje de WhatsApp.
- Usá los totales precalculados cuando sirvan; no hagas cuentas por tu cuenta si ya están.
- Si no hay registros que respondan la pregunta, decilo sin inventar nada.
- Podés usar *negrita* de WhatsApp para destacar números. No uses tablas ni markdown con #.
"""


def _chat_json(system: str, usuario: str) -> dict:
    respuesta = _groq().chat.completions.create(
        model=config.GROQ_MODELO,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": usuario}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    return json.loads(respuesta.choices[0].message.content)


_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def interpretar(texto: str, hoy: date) -> dict:
    system = PROMPT_INTERPRETAR.format(hoy=hoy.isoformat(), dia_semana=_DIAS[hoy.weekday()])
    return _chat_json(system, texto)


def redactar_respuesta(pregunta: str, datos: dict, hoy: date) -> str:
    respuesta = _groq().chat.completions.create(
        model=config.GROQ_MODELO,
        messages=[
            {"role": "system", "content": PROMPT_RESPONDER.format(hoy=hoy.isoformat())},
            {
                "role": "user",
                "content": f"Pregunta: {pregunta}\n\nDatos:\n{json.dumps(datos, ensure_ascii=False, default=str)}",
            },
        ],
        temperature=0.3,
    )
    return respuesta.choices[0].message.content.strip()


def transcribir(audio: bytes, nombre_archivo: str = "audio.ogg") -> str:
    resultado = _groq().audio.transcriptions.create(
        file=(nombre_archivo, audio),
        model=config.GROQ_MODELO_AUDIO,
        language="es",
    )
    return resultado.text.strip()
