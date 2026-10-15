"""Lo que el módulo común le suma al prompt: el cuaderno, las consultas, los precios y SENASA."""

from app.ia.prompt import Parte

PROMPT = Parte(
    intenciones=(
        "registrar",
        "corregir",
        "borrar",
        "consultar",
        "aclarar",
        "saludo",
        "establecimiento",
        "precio",
        "producto_veterinario",
    ),
    campos="""\
  "eventos": [ EVENTO, ... ],      // solo si intencion = "registrar"; un mensaje puede traer varios eventos
  "correccion": CORRECCION | null, // solo si intencion = "corregir"
  "borrado": BORRADO | null,       // solo si intencion = "borrar"
  "falta": [ ... ] | null,         // solo si intencion = "aclarar": qué datos faltan, de esta lista:
                                   // "que_paso", "establecimiento", "cual_registro", "que_cambiar",
                                   // "cantidad", "producto", "fecha", "que_producto_precio"
  "agradece": bool | null,         // solo si intencion = "saludo": true si es un agradecimiento
  "consulta": CONSULTA | null,     // solo si intencion = "consultar"
  "precio": PRECIO | null,         // solo si intencion = "precio"
  "producto_veterinario": { "nombre": string } | null  // solo si intencion = "producto_veterinario\"""",
    descripciones="""\
- "registrar": el usuario informa algo que hizo o pasó (vacunó, nacieron, llovió, pesó, hizo tacto...).
- "corregir": cambia o completa algo que YA anotó antes, en vez de contar algo nuevo. Se reconoce
  porque se refiere a un registro anterior: "a esas 5 vaquillonas las vacuné con ivermectina",
  "eran 30, no 20", "me equivoqué, fue en el lote 4", "lo de recién fue ayer", "corregí: ...".
  Si cuenta algo que hizo además de lo anterior ("también desparasité 10 terneros"), es "registrar".
- "borrar": pide borrar o eliminar uno o varios registros que anotó ("borrá la lluvia de La Pastora",
  "eliminá las 5 vaquillonas y la cosecha del lote 5", "sacá lo último").
- "consultar": pregunta por cosas que ÉL MISMO anotó antes, o pide la lista de lo que tiene
  anotado ("¿qué tengo anotado?", "pasame la lista de La Pastora") ("¿qué hice hoy?", "¿qué hice en La Esperanza?").
- "establecimiento": solo avisa dónde está o a qué campo llegó, sin registrar nada
  ("estoy en La Esperanza", "llegué a El Ombú"). Completá "establecimiento".
- "precio": pide el precio o cotización actual de un grano o de hacienda (soja, maíz, trigo,
  girasol, sorgo, cebada, novillo, vaca, ternero, vaquillona, toro...).
- "producto_veterinario": quiere saber si un producto veterinario (vacuna, antiparasitario,
  antibiótico, etc.) está registrado o aprobado por SENASA. "nombre" es el nombre comercial o
  el principio activo tal como lo escribió (ej: "ivermectina", "Aftosa Bioaftogen").
- "aclarar": el pedido SÍ es de lo que hace el sistema pero falta un dato sin el cual no se puede
  hacer (ej: "anotá" sin decir qué; "corregí eso" sin decir qué cambiar). No lo uses si el dato
  se puede deducir del mensaje o de la conversación reciente. Que falte el establecimiento NO
  impide registrar: registrá igual.
- "saludo": saludos, agradecimientos, "ok", "dale", "buen día" sin ningún pedido.""",
    pedidos="""\
Cada producto de un pedido de precios es una acción "precio" aparte (soja y maíz = dos acciones).
Varios eventos que se anotan juntos van en UNA acción "registrar" con varios eventos.""",
    formatos="""\
EVENTO:
{
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
}

Tipos por categoría:
- sanidad: vacunacion, desparasitacion, tratamiento, otro
- movimiento: nacimiento, muerte, compra, venta, traslado, otro
- pesada: pesaje
- reproduccion: servicio, tacto, paricion, destete, inseminacion, otro
- campo: lluvia, siembra, cosecha, fumigacion, fertilizacion, mantenimiento, otro

CORRECCION:
{
  "referencia": { ... },  // datos que IDENTIFICAN el registro a corregir, tal como los menciona
                            // ("esas 5 vaquillonas" -> {"cantidad_animales": 5, "categoria_animal": "vaquillonas"}).
                            // Mismas claves que EVENTO. Vacío {} si dice "lo último", "lo de recién", etc.
  "cambios": { ... }      // SOLO los datos nuevos o corregidos que dice el mensaje, con las mismas claves
                            // que EVENTO (más "establecimiento"). No repitas lo que no cambia.
}

BORRADO:
{
  "registros": [ REFERENCIA, ... ]  // una por cada cosa que pide borrar; [] si dice "lo último"
}
REFERENCIA: mismas claves que EVENTO (solo las que menciona para identificarlo) más
  "establecimiento" y "todos": true SOLO si pide explícitamente borrar todos los que coincidan.
  Si una frase aplica a varias cosas ("ambos del campo La Pastora"), repetí ese dato en cada una.
  Si dice "todo lo de la lista", "todo eso", "borralos" después de que el sistema le mostró una
  lista, usá UNA referencia con los mismos filtros de esa consulta (establecimiento, tipo, fechas
  como "desde"/"hasta"...) y "todos": true.
  Si pide borrar TODO lo que tiene anotado ("borrá todo", "todo de todos los campos", "de todos
  lados", "vaciá el cuaderno"), aunque antes haya visto una lista filtrada: [{"todos": true}],
  sin establecimiento ni otros filtros.
  Ej: "borrá las 5 vaquillonas y la cosecha del lote 5, ambos de La Pastora" ->
  [{"cantidad_animales": 5, "categoria_animal": "vaquillonas", "establecimiento": "La Pastora"},
   {"tipo": "cosecha", "lote": "5", "establecimiento": "La Pastora"}]

CONSULTA (filtros para buscar en la base; poné null en lo que no se pida; si pide "todo lo
anotado", dejá todos los filtros en null):
{
  "categoria": string | null,
  "tipo": string | null,
  "lote": string | null,
  "caravana": string | null,
  "categoria_animal": string | null,
  "producto": string | null,
  "establecimiento": string | null,   // si pregunta por un establecimiento puntual
  "desde": "YYYY-MM-DD" | null,
  "hasta": "YYYY-MM-DD" | null
}

PRECIO:
{
  "rubro": "granos" | "hacienda" | null,
  "producto": string | null     // en singular y minúscula, sin tildes: "soja", "maiz", "novillo"...
}""",
    reglas="""\
- Fechas relativas ("ayer", "el lunes", "la semana pasada") convertilas a YYYY-MM-DD usando la fecha de hoy.
  Si no se menciona fecha en un registro, usá la de hoy.
- En consultas como "este mes" o "este año", completá "desde" y "hasta".
- NUNCA inventes datos. Si falta algo, null. Si el mensaje es ambiguo, confianza "baja".
- Las preguntas ("¿cuántas...?", "¿cuándo...?", "¿qué se le dio...?") son "consultar", no "registrar".
- El lote o potrero NO es el establecimiento: "lote 3" va en "lote"; "La Esperanza" en "establecimiento".""",
)
