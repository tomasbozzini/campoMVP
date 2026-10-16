"""Perfil de cada persona: nombre y apellido, rubro, localidad y matrícula.

Se completa con preguntas fijas, sin IA: quien escribe sin tener los tres datos del alta
(nombre y apellido, rubro y localidad) los responde antes de seguir. Lo que mandó no se
anota y al final se le pide que lo repita. La matrícula es opcional y se carga aparte.

El rubro define qué módulos usa la persona (ver `modulos.MODULOS_POR_RUBRO`).

Lo que pasa acá no se guarda en la charla que ve la IA: trae datos personales que la IA no
necesita.
"""

import re

from app.infra.modelos import Usuario
from app.infra.texto import prolijo, sin_tildes
from app.nucleo.contexto import Contexto
from app.salidas.whatsapp import SEPARADOR as LINEA

RUBROS = {
    "veterinario": "Veterinario",
    "agronomo": "Agrónomo o asesor",
    "productor": "Productor",
}

# Las preguntas del alta, en orden, con el dato que completan.
ALTA = {"nombre": "nombre_completo", "rubro": "rubro", "localidad": "localidad"}
CAMBIO_RUBRO = "cambio_rubro"
CAMBIO_MATRICULA = "cambio_matricula"

VER_DATOS = {"mis datos", "mi perfil", "perfil"}
CAMBIAR_RUBRO = {"cambiar rubro", "cambiar mi rubro"}
CAMBIAR_MATRICULA = {"cambiar matricula", "cambiar mi matricula", "cargar matricula", "cargar mi matricula"}
CANCELAR = {"cancelar", "cancela", "no", "nada"}
SIN_MATRICULA = {"ninguna", "no tengo", "sin matricula", "borrar", "borrarla"}

PREGUNTAS = {
    "nombre": "¿Cuál es tu *nombre y apellido*?",
    "rubro": (
        "¿A qué te dedicás? Respondé con el número:\n"
        "      *1* Veterinario\n"
        "      *2* Agrónomo o asesor\n"
        "      *3* Productor"
    ),
    "localidad": "¿De qué *localidad* sos? Por ejemplo: _Tandil_.",
}
NO_ENTENDI = {
    "nombre": "🤔 Necesito tu nombre y apellido, por ejemplo: _Juan Pérez_.",
    "rubro": "🤔 No entendí. Elegí una opción del 1 al 3.",
    "localidad": "🤔 No entendí la localidad. Escribila sola, por ejemplo: _Tandil_.",
}

LISTO = (
    "✅ *¡Listo, {nombre}!*\n\n"
    "Ya tengo tus datos. Los ves con *mis datos*.\n"
    "Si antes de estas preguntas me habías mandado algo, mandámelo de nuevo: todavía no lo anoté.\n\n"
    "Mandá *ayuda* para ver qué podés hacer."
)

PREGUNTA_MATRICULA = (
    "¿Cuál es tu *matrícula*? Escribila como figura, por ejemplo: _MP 1234_.\n_Para borrarla, mandá *ninguna*._"
)
SIN_CAMBIOS = "👌 Listo, no cambié nada."
RUBRO_DE_NUEVO = "Cambiaron las opciones de rubro: necesito que vuelvas a elegir el tuyo."

# Palabras que identifican cada rubro en una respuesta escrita (sin tildes, minúscula).
_PALABRAS_RUBRO = {
    "veterinario": ("veterinari", "vete"),
    "agronomo": ("agronom", "asesor"),
    "productor": ("productor",),
}
_NUMEROS_RUBRO = {"1": "veterinario", "2": "agronomo", "3": "productor"}
_PREFIJOS_NOMBRE = ("me llamo ", "mi nombre es ", "soy ")
_PREFIJOS_LOCALIDAD = ("soy de ", "vivo en ", "estoy en ", "de ", "en ")
_LETRAS_NOMBRE = re.compile(r"^[^\W\d_]+(?:['.\-][^\W\d_]*)*$")
# Hasta dos siglas cortas y el número: "MP 1234", "M.P. 1234", "CMVPBA 5678", "1234/5".
_MATRICULA = re.compile(r"^(?:[A-Za-z.]{1,7} ?){0,2}\d[\d./\-]*$")


def _normalizar(texto: str) -> str:
    return " ".join(sin_tildes(texto.lower().strip(" !.¡¿?")).split())


def _sin_prefijo(texto: str, prefijos: tuple[str, ...]) -> str:
    limpio = " ".join(texto.strip(" .!¡¿?,;").split())
    for prefijo in prefijos:
        if limpio.lower().startswith(prefijo):
            return limpio[len(prefijo) :]
    return limpio


def leer_nombre(texto: str) -> str | None:
    """Nombre y apellido: al menos dos palabras, solo letras. None si no parece un nombre."""
    nombre = _sin_prefijo(texto, _PREFIJOS_NOMBRE)
    palabras = nombre.split()
    if len(palabras) < 2 or len(nombre) > 80 or not all(_LETRAS_NOMBRE.match(p) for p in palabras):
        return None
    return prolijo(nombre)


def leer_rubro(texto: str) -> str | None:
    """El rubro elegido, por número (1 a 3) o por nombre. None si no se entiende o hay más de uno."""
    respuesta = _normalizar(texto)
    numeros = set(re.findall(r"\d+", respuesta))
    if len(numeros) == 1 and (numero := numeros.pop()) in _NUMEROS_RUBRO and len(respuesta) <= 12:
        return _NUMEROS_RUBRO[numero]
    elegidos = {
        rubro for rubro, palabras in _PALABRAS_RUBRO.items() if any(p in w for w in respuesta.split() for p in palabras)
    }
    return elegidos.pop() if len(elegidos) == 1 else None


def leer_localidad(texto: str) -> str | None:
    localidad = _sin_prefijo(texto, _PREFIJOS_LOCALIDAD)
    if not localidad or len(localidad) > 80 or not re.search(r"[^\W\d_]", localidad):
        return None
    return prolijo(localidad)


def leer_matricula(texto: str) -> str | None:
    """Una matrícula como la escribe la persona ("MP 1234"). None si no tiene esa forma."""
    matricula = " ".join(texto.split())
    return matricula if len(matricula) <= 30 and _MATRICULA.match(matricula) else None


_LECTORES = {"nombre": leer_nombre, "rubro": leer_rubro, "localidad": leer_localidad}


def _tiene(usuario: Usuario, campo: str) -> bool:
    """Si el dato está respondido. Un rubro que ya no se ofrece (el "otro" de antes) cuenta
    como sin responder: se vuelve a preguntar."""
    valor = getattr(usuario, campo)
    return valor in RUBROS if campo == "rubro" else bool(valor)


def falta(usuario: Usuario) -> str | None:
    """La primera pregunta del alta que falta responder; None si el perfil está completo."""
    return next((pregunta for pregunta, campo in ALTA.items() if not _tiene(usuario, campo)), None)


def intro(usuario: Usuario, titulo: str = "👋 *¡Hola! Soy CampoBot.*") -> str:
    """La presentación antes de la primera pregunta, con cuántos datos faltan."""
    faltan = sum(1 for campo in ALTA.values() if not _tiene(usuario, campo))
    if faltan == 1 and usuario.rubro:
        return f"{titulo}\n\n{RUBRO_DE_NUEVO}\n\n"
    datos = "un dato tuyo" if faltan == 1 else f"{faltan} datos tuyos"
    return f"{titulo}\n\nAntes de seguir necesito {datos}. Es una sola vez.\n\n"


def alta(ctx: Contexto, respuesta_fija: str | None) -> str:
    """Para quien todavía no completó el alta: guarda la respuesta a la pregunta pendiente y
    hace la siguiente. `respuesta_fija` es la de un comando que se responde igual durante el
    alta (ayuda, privacidad): se muestra y se repite la pregunta."""
    usuario = ctx.usuario
    if usuario.pregunta in ALTA and respuesta_fija is None:
        valor = _LECTORES[usuario.pregunta](ctx.texto)
        if valor is None:
            return f"{NO_ENTENDI[usuario.pregunta]}\n\n{PREGUNTAS[usuario.pregunta]}"
        setattr(usuario, ALTA[usuario.pregunta], valor)
        usuario.pregunta = falta(usuario)
        if usuario.pregunta is None:
            return LISTO.format(nombre=(usuario.nombre_completo or "").split()[0])
        return PREGUNTAS[usuario.pregunta]

    presentacion = "" if usuario.pregunta in ALTA else intro(usuario)
    usuario.pregunta = falta(usuario)
    pregunta = presentacion + PREGUNTAS[usuario.pregunta or "nombre"]
    return f"{respuesta_fija}\n\n{LINEA}\n{pregunta}" if respuesta_fija else pregunta


def _rubro(usuario: Usuario) -> str:
    return RUBROS.get(usuario.rubro or "", "sin elegir")


def mis_datos(usuario: Usuario) -> str:
    matricula = usuario.matricula or "_sin cargar_"
    return (
        "👤 *MIS DATOS*\n\n"
        f"      › Nombre: {usuario.nombre_completo}\n"
        f"      › Rubro: {_rubro(usuario)}\n"
        f"      › Localidad: {usuario.localidad}\n"
        f"      › Matrícula: {matricula}\n\n"
        f"{LINEA}\n"
        "*cambiar rubro* → elegir otro rubro\n"
        "*cambiar matrícula* → cargar, cambiar o borrar tu matrícula\n"
        "*privacidad* → cómo se usan tus datos"
    )


def _resolver_cambio(usuario: Usuario, pregunta: str, texto: str) -> str | None:
    """La respuesta a "cambiar rubro" o "cambiar matrícula". None si el mensaje no es una
    respuesta: el cambio se descarta y el mensaje sigue su camino normal."""
    respuesta = _normalizar(texto)
    if respuesta in CANCELAR:
        return SIN_CAMBIOS
    if pregunta == CAMBIO_RUBRO:
        rubro = leer_rubro(texto)
        if rubro is None:
            return None
        usuario.rubro = rubro
        return f"✅ Listo, ahora figurás como *{RUBROS[rubro]}*."
    if respuesta in SIN_MATRICULA:
        usuario.matricula = None
        return "✅ Listo, borré tu matrícula."
    matricula = leer_matricula(texto)
    if matricula is None:
        return None
    usuario.matricula = matricula
    return f"✅ Listo, tu matrícula es *{matricula}*.\nVa a figurar en tus reportes en PDF."


def ver_datos(ctx: Contexto) -> str:
    """Mis datos: el atajo o el pedido con cualquier frase."""
    ctx.guardar_charla = False  # trae nombre, localidad, matrícula
    return mis_datos(ctx.usuario)


def pedir_rubro(ctx: Contexto) -> str:
    """Cambiar rubro: muestra el actual y pregunta el nuevo."""
    ctx.guardar_charla = False
    ctx.usuario.pregunta = CAMBIO_RUBRO
    return f"Ahora figurás como *{_rubro(ctx.usuario)}*.\n\n{PREGUNTAS['rubro']}"


def pedir_matricula(ctx: Contexto) -> str:
    """Cambiar matrícula: pregunta la nueva."""
    ctx.guardar_charla = False
    ctx.usuario.pregunta = CAMBIO_MATRICULA
    return PREGUNTA_MATRICULA


def comando(ctx: Contexto) -> str | None:
    """Los atajos del perfil (mis datos, cambiar rubro, cambiar matrícula) y las respuestas
    a sus preguntas. None si el mensaje no es para el perfil. Pedidos con otras palabras
    llegan por la IA a las mismas funciones (`modulos/comun/cuenta.py`)."""
    usuario = ctx.usuario
    pendiente, usuario.pregunta = usuario.pregunta, None
    if pendiente in (CAMBIO_RUBRO, CAMBIO_MATRICULA) and (respuesta := _resolver_cambio(usuario, pendiente, ctx.texto)):
        ctx.guardar_charla = False
        return respuesta
    pedido = _normalizar(ctx.texto)
    if pedido in VER_DATOS:
        return ver_datos(ctx)
    if pedido in CAMBIAR_RUBRO:
        return pedir_rubro(ctx)
    if pedido in CAMBIAR_MATRICULA:
        return pedir_matricula(ctx)
    return None
