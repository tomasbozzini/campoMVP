"""Groq: el modelo que interpreta los mensajes y Whisper para los audios."""

import json

from groq import Groq


class ProveedorGroq:
    def __init__(self, api_key: str, modelo: str, modelo_audio: str) -> None:
        self._cliente = Groq(api_key=api_key)
        self._modelo = modelo
        self._modelo_audio = modelo_audio

    def completar_json(self, sistema: str, mensaje: str) -> object:
        respuesta = self._cliente.chat.completions.create(
            model=self._modelo,
            messages=[{"role": "system", "content": sistema}, {"role": "user", "content": mensaje}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_completion_tokens=3000,
        )
        return json.loads(respuesta.choices[0].message.content or "{}")

    def transcribir(self, audio: bytes, nombre_archivo: str) -> str:
        resultado = self._cliente.audio.transcriptions.create(
            file=(nombre_archivo, audio),
            model=self._modelo_audio,
            language="es",
        )
        return resultado.text.strip()
