"""Groq: el modelo que interpreta los mensajes y Whisper para los audios."""

import json

from groq import APIError, Groq

from app.ia.proveedor import ErrorIA


def _error(e: APIError) -> ErrorIA:
    """Solo el tipo y el código: el cuerpo de un error de Groq puede traer el texto de la
    persona (por ejemplo, en failed_generation)."""
    codigo = getattr(e, "status_code", None)
    return ErrorIA(type(e).__name__ + (f" {codigo}" if codigo else ""))


class ProveedorGroq:
    def __init__(self, api_key: str, modelo: str, modelo_audio: str) -> None:
        self._cliente = Groq(api_key=api_key)
        self._modelo = modelo
        self._modelo_audio = modelo_audio

    def completar_json(self, sistema: str, mensaje: str) -> object:
        try:
            respuesta = self._cliente.chat.completions.create(
                model=self._modelo,
                messages=[{"role": "system", "content": sistema}, {"role": "user", "content": mensaje}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_completion_tokens=3000,
            )
        except APIError as e:
            raise _error(e) from None  # sin el error original, que lleva el cuerpo
        return json.loads(respuesta.choices[0].message.content or "{}")

    def transcribir(self, audio: bytes, nombre_archivo: str) -> str:
        try:
            resultado = self._cliente.audio.transcriptions.create(
                file=(nombre_archivo, audio),
                model=self._modelo_audio,
                language="es",
            )
        except APIError as e:
            raise _error(e) from None
        return resultado.text.strip()
