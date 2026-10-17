"""Groq: Whisper para los audios y el modelo que interpreta los mensajes (de respaldo si
está OpenRouter)."""

import json
import time

from groq import APIConnectionError, APIError, Groq, InternalServerError, RateLimitError, omit

from app.ia.proveedor import ErrorIA, IASaturada, Uso, anotar_uso


def _error(e: APIError) -> ErrorIA:
    """Solo el tipo y el código: el cuerpo de un error de Groq puede traer el texto de la
    persona (por ejemplo, en failed_generation). Límite de pedidos, sin respuesta o caído:
    la IA está saturada, no es culpa del mensaje."""
    codigo = getattr(e, "status_code", None)
    clase = IASaturada if isinstance(e, RateLimitError | APIConnectionError | InternalServerError) else ErrorIA
    return clase(type(e).__name__ + (f" {codigo}" if codigo else ""))


def _entero(valor: object) -> int:
    return valor if isinstance(valor, int) else 0


class ProveedorGroq:
    def __init__(self, api_key: str, modelo: str, modelo_audio: str) -> None:
        self._cliente = Groq(api_key=api_key)
        self._modelo = modelo
        self._modelo_audio = modelo_audio

    def completar_json(self, sistema: str, mensaje: str) -> object:
        inicio = time.perf_counter()
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
        uso = getattr(respuesta, "usage", None)
        detalle = getattr(uso, "completion_tokens_details", None)
        anotar_uso(
            Uso(
                proveedor="groq",
                servidor=None,
                tokens_entrada=_entero(getattr(uso, "prompt_tokens", 0)),
                tokens_salida=_entero(getattr(uso, "completion_tokens", 0)),
                tokens_razonamiento=_entero(getattr(detalle, "reasoning_tokens", 0)),
                costo_usd=None,  # Groq no lo informa
                segundos=time.perf_counter() - inicio,
            )
        )
        contenido = respuesta.choices[0].message.content
        if not contenido:
            raise ErrorIA("Groq devolvió una respuesta vacía")
        try:
            return json.loads(contenido)
        except json.JSONDecodeError:
            raise ErrorIA("Groq devolvió un JSON inválido") from None

    def transcribir(self, audio: bytes, nombre_archivo: str, glosario: str) -> str:
        try:
            resultado = self._cliente.audio.transcriptions.create(
                file=(nombre_archivo, audio),
                model=self._modelo_audio,
                language="es",
                # Whisper lo toma como texto anterior al audio: copia cómo se escriben esas palabras.
                prompt=glosario or omit,
            )
        except APIError as e:
            raise _error(e) from None
        return resultado.text.strip()
