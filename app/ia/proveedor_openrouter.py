"""OpenRouter: interpreta los mensajes con el mismo modelo que Groq (API compatible con OpenAI).

OpenRouter elige qué servidor corre el modelo. Le pedimos solo los de retención cero (`zdr`),
que no guardan ni entrenan con los datos (`data_collection: deny`) y que aceptan todos los
parámetros del pedido (`require_parameters`), así la salida en JSON está garantizada. Entre
esos, primero Cerebras y después Groq (`order`), y si los dos fallan prueba otro
(`allow_fallbacks`) antes de que conteste el respaldo. Dejarlo elegir no alcanza: por precio,
los servidores tardan unos 5 s, y ordenados por velocidad (`sort: throughput`) parte de los
pedidos va a uno que tarda de 4 a 8 s (paso 8.4 del plan).
"""

import json
import time
from typing import Any

import httpx

from app.ia.proveedor import ErrorIA, IASaturada, Uso, anotar_uso
from app.infra.marca import NOMBRE

URL = "https://openrouter.ai/api/v1/chat/completions"
# Para que WhatsApp no espere de más: si no responde, contesta el respaldo. Es el tope del
# pedido entero: mientras procesa, OpenRouter manda espacios para mantener viva la conexión, y
# el tiempo de espera de httpx se reinicia con cada uno.
ESPERA = 6.0  # segundos (la p95 del eval con Cerebras es de unos 2 s)
# Los servidores más rápidos para este modelo, en orden (con retención cero, como todos).
SERVIDORES = ["cerebras", "groq"]
# Códigos que no son culpa del pedido: 402 sin saldo, 408 sin respuesta, 429 límite de
# pedidos, 5xx sin servidores disponibles.
_SATURADA = {402, 408, 429, 500, 502, 503, 504}


def _error(codigo: object) -> ErrorIA:
    """Solo el código: el cuerpo de un error puede traer el texto de la persona."""
    clase = IASaturada if codigo in _SATURADA else ErrorIA
    return clase(f"OpenRouter {codigo}")


def _entero(valor: object) -> int:
    return valor if isinstance(valor, int) else 0


class ProveedorOpenRouter:
    def __init__(
        self, api_key: str, modelo: str, esfuerzo: str, cliente: httpx.Client | None = None, espera: float = ESPERA
    ) -> None:
        self._api_key = api_key
        self._modelo = modelo
        self._esfuerzo = esfuerzo
        self._espera = espera
        # Conectarse tiene su propia espera, que httpx puede gastar más de una vez (con IPv6 y
        # con IPv4): con la mitad, el pedido entero sigue dentro de la espera.
        self._cliente = cliente or httpx.Client(timeout=httpx.Timeout(espera, connect=espera / 2))

    def pedido(self, sistema: str, mensaje: str) -> dict[str, Any]:
        return {
            "model": self._modelo,
            "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": mensaje}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 3000,
            "reasoning": {"effort": self._esfuerzo},
            "provider": {
                "zdr": True,
                "data_collection": "deny",
                "require_parameters": True,
                "order": SERVIDORES,
                "allow_fallbacks": True,
            },
            "usage": {"include": True},
        }

    def _enviar(self, cuerpo: dict[str, Any], inicio: float) -> tuple[int, bytes]:
        """El código y el cuerpo de la respuesta, cortando si el pedido entero pasa la espera."""
        partes: list[bytes] = []
        try:
            with self._cliente.stream(
                "POST", URL, json=cuerpo, headers={"Authorization": f"Bearer {self._api_key}", "X-Title": NOMBRE}
            ) as respuesta:
                for parte in respuesta.iter_bytes():
                    partes.append(parte)
                    if time.perf_counter() - inicio > self._espera:
                        raise IASaturada(f"OpenRouter sin respuesta en {self._espera:g} s")
                return respuesta.status_code, b"".join(partes)
        except httpx.HTTPError as e:
            raise IASaturada(f"OpenRouter {type(e).__name__}") from None

    def completar_json(self, sistema: str, mensaje: str) -> object:
        inicio = time.perf_counter()
        codigo, contenido_crudo = self._enviar(self.pedido(sistema, mensaje), inicio)
        if codigo != 200:
            raise _error(codigo)
        try:
            datos = json.loads(contenido_crudo)
        except ValueError:
            raise ErrorIA("OpenRouter devolvió algo que no es JSON") from None
        if not isinstance(datos, dict):
            raise ErrorIA("OpenRouter devolvió algo que no es JSON")
        if isinstance(datos.get("error"), dict):
            raise _error(datos["error"].get("code"))

        uso = datos.get("usage") or {}
        detalle = uso.get("completion_tokens_details") or {}
        entrada = uso.get("prompt_tokens_details") or {}
        costo = uso.get("cost")
        anotar_uso(
            Uso(
                proveedor="openrouter",
                servidor=datos.get("provider") if isinstance(datos.get("provider"), str) else None,
                tokens_entrada=_entero(uso.get("prompt_tokens")),
                tokens_salida=_entero(uso.get("completion_tokens")),
                tokens_razonamiento=_entero(detalle.get("reasoning_tokens")),
                costo_usd=float(costo) if isinstance(costo, int | float) else None,
                segundos=time.perf_counter() - inicio,
                tokens_cache=_entero(entrada.get("cached_tokens")),
            )
        )
        try:
            contenido = datos["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            contenido = None
        if not contenido:
            raise ErrorIA("OpenRouter devolvió una respuesta vacía")
        try:
            return json.loads(contenido)
        except json.JSONDecodeError:
            raise ErrorIA("OpenRouter devolvió un JSON inválido") from None
