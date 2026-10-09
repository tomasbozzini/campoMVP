from groq import Groq
from dotenv import load_dotenv
from datetime import date
import os

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

system_prompt = f"""Sos un asistente que interpreta mensajes de productores ganaderos sobre eventos sanitarios de sus animales.

Devolvé ÚNICAMENTE un objeto JSON válido con esta estructura exacta:

{{
    "tipo_evento": "vacunacion" | "desparasitacion" | "tratamiento" | "otro",
    "descripcion": string | null,      // qué se aplicó (nombre de vacuna/medicamento/enfermedad tratada)
    "cantidad": string | null,          // SOLO dosis o cantidad de producto aplicado (ej: "2ml", "1 dosis"). NO la cantidad de animales.
    "animal_o_lote": string | null,     // sobre qué animal(es) fue: identificador, grupo o cantidad de animales (ej: "vaca 213", "40 terneros", "2 vacas")
    "fecha_evento": string | null,      // OBLIGATORIO formato YYYY-MM-DD si se puede inferir una fecha, aunque sea aproximada. Si NO se puede inferir ninguna fecha, usá null. NUNCA texto libre como "esta semana".
    "confianza": "alta" | "media" | "baja"
}}

La fecha de hoy es {date.today()}. Si el mensaje dice "esta semana" sin más precisión, usá la fecha de hoy como aproximación y bajá la confianza a "media" o "baja".
Si falta información para un campo, usá null. NUNCA inventes datos ni hagas preguntas. Tu única salida es el JSON.
"""

frases = [
    "Hoy vacuné 40 terneros contra aftosa",
    "Le di ivermectina a la vaca 213, dos mililitros, ayer a la tarde",
    "El lunes pasado desparasité todo el rodeo del potrero grande",
    "Che, les puse algo a los terneros esta semana, no me acuerdo bien cuál",
    "Estuvo lloviendo bastante, así que recién ahora pude vacunar dos vacas que estaban con mastitis",
]

for frase in frases:
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": frase},
        ],
        response_format={"type": "json_object"},  # fuerza salida JSON
        temperature=0.2,  # menos creatividad, más consistencia
    )
    print(f"MENSAJE: {frase}")
    print(f"RESPUESTA: {response.choices[0].message.content}\n")