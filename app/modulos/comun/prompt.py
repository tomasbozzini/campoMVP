"""Lo que el módulo común le suma al prompt: el cuaderno, las consultas, las sesiones, los
pendientes, lo de la cuenta (ayuda, privacidad, mis campos, mis datos), los precios y SENASA."""

from app.ia.prompt import Parte

PROMPT = Parte(
    intenciones=(
        "registrar",
        "corregir",
        "borrar",
        "consultar",
        "exportar",
        "aclarar",
        "saludo",
        "establecimiento",
        "abrir_sesion",
        "cerrar_sesion",
        "anotar_pendiente",
        "ver_pendientes",
        "pendiente_hecho",
        "borrar_pendiente",
        "corregir_pendiente",
        "cancelar",
        "mis_campos",
        "mis_datos",
        "cambiar_rubro",
        "cambiar_matricula",
        "privacidad",
        "ayuda",
        "borrar_mis_datos",
        "precio",
        "producto_veterinario",
    ),
    campos="""\
  "eventos": [ EVENTO, ... ],      // solo si intencion = "registrar"; un mensaje puede traer varios eventos
  "correccion": CORRECCION | null, // solo si intencion = "corregir"
  "borrado": BORRADO | null,       // solo si intencion = "borrar"
  "falta": [ ... ] | null,         // solo si intencion = "aclarar": qué datos faltan, de esta lista:
                                   // "que_paso", "establecimiento", "cual_registro", "que_cambiar",
                                   // "cantidad", "producto", "fecha", "que_producto_precio", "que_pedido"
  "agradece": bool | null,         // solo si intencion = "saludo": true si es un agradecimiento
  "consulta": CONSULTA | null,     // solo si intencion = "consultar" o "exportar"
  "exportar": { "formato": "pdf" | "excel" | "csv" } | null,  // solo si intencion = "exportar"
  "sesion": { "lote": string | null, "actividad": string | null } | null,  // solo si intencion = "abrir_sesion"
  "pendiente": PENDIENTE | null,   // solo si intencion = "anotar_pendiente"
  "pendientes": [ REF_PENDIENTE, ... ] | null,  // solo si intencion = "pendiente_hecho" o "borrar_pendiente"
  "correccion_pendiente": CORRECCION_PENDIENTE | null,  // solo si intencion = "corregir_pendiente"
  "precio": PRECIO | null,         // solo si intencion = "precio"
  "producto_veterinario": { "nombre": string } | null  // solo si intencion = "producto_veterinario\"""",
    descripciones="""\
- "registrar": el usuario informa algo que hizo o pasó (vacunó, nacieron, llovió, pesó, hizo tacto...).
- "corregir": cambia o completa un REGISTRO (algo que hizo) que YA anotó antes, en vez de contar
  algo nuevo. Se reconoce porque se refiere a un registro anterior: "a esas 5 vaquillonas las
  vacuné con ivermectina", "eran 30, no 20", "me equivoqué, fue en el lote 4", "lo de recién fue
  ayer", "corregí: ...". Si cuenta algo que hizo además de lo anterior ("también desparasité 10
  terneros"), es "registrar". Si corrige un PENDIENTE (algo por hacer), es "corregir_pendiente".
- "borrar": pide borrar o eliminar uno o varios registros que anotó ("borrá la lluvia de La Pastora",
  "eliminá las 5 vaquillonas y la cosecha del lote 5"), o deshacer lo último que anotó ("sacá lo
  último", "deshacé eso", "me equivoqué, borralo", "eso no va, sacalo"). Tachar algo porque ya
  lo hizo no es borrar: es "pendiente_hecho".
- "consultar": pregunta por cosas que ÉL MISMO anotó antes, o pide la lista de lo que tiene
  anotado ("¿qué tengo anotado?", "pasame la lista de La Pastora") ("¿qué hice hoy?", "¿qué hice en La Esperanza?").
  Lo que tiene pendiente o por hacer es "ver_pendientes"; la lista de sus campos o lotes, sin
  preguntar por lo anotado, es "mis_campos".
- "exportar": pide lo que anotó en un ARCHIVO para guardar o reenviar: PDF, Excel, planilla o CSV
  ("mandame un PDF de lo que hice en La Pastora este mes", "pasame la planilla de las
  vacunaciones", "quiero el informe de la semana para mandárselo al dueño"). Completá "consulta"
  con los filtros, como en "consultar". "formato": "excel" si dice Excel o planilla, "csv" solo
  si dice CSV; si no dice, "pdf". Muchos mensajes vienen de un audio transcripto: el formato
  puede llegar deletreado o escrito como suena ("c s v", "ce ese ve", "pe de efe", "ecsel"). Es
  el mismo formato, y pedir que le saquen, pasen o manden eso es "exportar", no "fuera_de_alcance".
- "establecimiento": solo avisa dónde está o a qué campo llegó, sin registrar nada
  ("estoy en La Esperanza", "llegué a El Ombú"). Completá "establecimiento".
- "abrir_sesion": avisa que EMPIEZA un trabajo en un lote, una manga o una tarea, para que lo que
  dicte después quede junto ("arranco manga en El Retiro", "empiezo siembra lote Los Pinos",
  "arrancamos tacto de vaquillonas en La Pastora"). Completá "establecimiento" si lo nombra y en
  "sesion" el lote (como en EVENTO) y la actividad en pocas palabras y en minúscula ("manga",
  "siembra", "tacto vaquillonas"). Si solo dice dónde está, sin decir que empieza un trabajo, es
  "establecimiento".
- "cerrar_sesion": avisa que TERMINÓ ese trabajo o pide cerrar la sesión ("terminamos", "cerramos
  la manga", "listo, terminé la siembra", "cerrá la sesión", "bueno, ya está, cortamos acá").
- "anotar_pendiente": algo que TIENE QUE HACER más adelante y quiere tener presente ("tengo que
  volver a revisar las vaquillonas el martes", "acordate de pedir vacunas", "pendiente: llamar al
  veterinario", "en 21 días toca la segunda dosis en El Ombú"). No es "registrar": todavía no pasó.
  También lo que TENÍA que hacer y no dice que lo hizo ("tenía que vacunar los terneros el lunes",
  "había que arreglar el alambrado ayer"): sigue pendiente, con la fecha pasada.
- "ver_pendientes": pregunta qué tiene pendiente o por hacer ("¿qué tengo pendiente?",
  "pendientes", "¿qué me falta hacer en El Ombú?"). Completá "establecimiento" si pregunta por un campo.
- "pendiente_hecho": avisa que ya hizo algo que tenía pendiente, o pide tacharlo o marcarlo como
  hecho ("ya está lo del lote 3", "ya llamé al veterinario", "listo lo de las vacunas", "marcá
  como hecho lo de Juan"). Se reconoce porque nombra algo por hacer con "lo de..." o "eso de..."
  y dice que ya está, listo o ya lo hizo, aunque no diga la palabra "pendiente". "Tenía que..." o
  "había que..." sin decir que lo hizo NO es "pendiente_hecho": es "anotar_pendiente". "Tachá" o
  "marcá" algo, contando que ya lo hizo, es siempre "pendiente_hecho". Las gestiones (comprar, llamar, pedir, revisar,
  avisar) son lo típico de un pendiente: "ya compré el alambre" o "ya revisé el molino" son
  "pendiente_hecho", no "registrar", porque no traen datos de un trabajo en el campo. Si además
  cuenta un trabajo con datos para anotar ("ya vacuné las 30 vaquillonas que tenía pendientes"),
  van "registrar" y "pendiente_hecho".
- "borrar_pendiente": pide sacar un pendiente que NO hizo, porque ya no va o se anotó mal ("borrá
  el pendiente de llamar a Juan", "sacá lo de las vacunas de los pendientes, al final no va").
  Tachar un pendiente porque ya lo hizo es "pendiente_hecho". Si habla de algo que anotó como
  hecho, es "borrar".
- "corregir_pendiente": cambia la fecha, el texto, el campo o el lote de uno o varios pendientes
  que ya anotó ("el pendiente de las aguadas es para el jueves", "lo de llamar a Juan pasalo al
  viernes", "los del molino no son de El Ombú, son de La Feliz"). Si la conversación reciente
  muestra que lo último que anotó fue un pendiente ("PENDIENTE ANOTADO") y corrige sin decir
  cuál ("perdón, el martes no, el miércoles", "no, era en el lote 4"), es "corregir_pendiente"
  sobre ese, no "corregir".
- "cancelar": SOLO si viene una PREGUNTA_PENDIENTE y el mensaje la rechaza o la cancela (ver arriba).
- "mis_campos": quiere ver la lista de sus campos, establecimientos o lotes ("quiero ver mis
  campos", "¿qué campos tengo cargados?", "mostrame los establecimientos", "pasame los lotes que tengo").
- "mis_datos": quiere ver los datos de su perfil: nombre, rubro, localidad o matrícula ("mostrame
  mis datos", "¿qué datos míos tenés?", "¿cómo figuro?", "mi perfil").
- "cambiar_rubro": quiere cambiar su rubro o a qué se dedica ("quiero cambiar mi rubro", "me
  anotaste mal, soy agrónomo", "cambiame la profesión").
- "cambiar_matricula": quiere cargar, cambiar o borrar su matrícula ("quiero cargar mi matrícula",
  "cambiame la matrícula", "sacá mi matrícula").
- "privacidad": pregunta cómo se usan o se guardan sus datos, quién ve lo que anota, o pide la
  política de privacidad ("¿quién ve lo que anoto?", "¿cómo usan mis datos?", "quiero ver lo de privacidad").
- "ayuda": pregunta qué puede hacer el sistema o cómo se usa, o pide ayuda o el menú ("¿qué podés
  hacer?", "¿cómo funciona esto?", "mandame el menú", "no sé cómo usarte").
- "borrar_mis_datos": pide borrar TODOS sus datos o su cuenta, darse de baja o que no quede nada
  suyo ("quiero borrar mi cuenta", "eliminá todos mis datos", "dame de baja"). Borrar lo anotado
  en el cuaderno ("borrá todo lo anotado") es "borrar".
- "precio": pide el precio o cotización actual de un grano o de hacienda (soja, maíz, trigo,
  girasol, sorgo, cebada, novillo, vaca, ternero, vaquillona, toro...).
- "producto_veterinario": quiere saber si un producto veterinario (vacuna, antiparasitario,
  antibiótico, etc.) está registrado o aprobado por SENASA. "nombre" es el nombre comercial o
  el principio activo tal como lo escribió (ej: "ivermectina", "Aftosa Bioaftogen").
- "aclarar": el pedido SÍ es de lo que hace el sistema pero falta un dato sin el cual no se puede
  hacer (ej: "anotá" sin decir qué; "corregí eso" sin decir qué cambiar). No lo uses si el dato
  se puede deducir del mensaje o de la conversación reciente. Que falte el establecimiento NO
  impide registrar: registrá igual. Si pide algo del sistema pero no se entiende qué ("quiero
  ver", "mostrame eso", "pasame lo mío" sin nada antes en la conversación), "falta":
  ["que_pedido"]: no adivines.
- "saludo": saludos, agradecimientos, "ok", "dale", "buen día" sin ningún pedido.""",
    pedidos="""\
Cada producto de un pedido de precios es una acción "precio" aparte (soja y maíz = dos acciones).
Varios eventos que se anotan juntos van en UNA acción "registrar" con varios eventos.
Si cuenta lo que hizo y que terminó ("vacuné 30 terneros y terminamos"), van el "registrar" y
después el "cerrar_sesion".""",
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

PENDIENTE:
{
  "texto": string,              // qué tiene que hacer, corto (hasta 120 letras) y con sus palabras (ej: "revisar las vaquillonas"), sin la fecha ni el campo
  "lote": string | null,        // como en EVENTO
  "vence": "YYYY-MM-DD" | null  // para cuándo, si lo dice. Si dice lo que TIENE que hacer, futura ("el martes" =
                                // el de "Los 7 días siguientes"); si dice lo que TENÍA que hacer o se olvidó,
                                // pasada ("tenía que… el lunes" = el de "Los 7 días anteriores")
}

REF_PENDIENTE (uno por cada pendiente que nombra):
{
  "texto": string | null,       // las palabras con las que lo nombra ("llamar al veterinario", "vacunas")
  "lote": string | null,        // como en EVENTO
  "establecimiento": string | null,
  "todos": bool                 // true SOLO si dice explícitamente todos ("ya hice todo lo de El Ombú")
}
  Si se refiere a uno que el sistema le mostró recién ("el segundo", "ese"), copiá su texto.
  Si nombra varios en plural ("los molinos", "los de El Ombú"), "todos": true.

CORRECCION_PENDIENTE:
{
  "pendientes": [ REF_PENDIENTE, ... ],  // cuáles corrige, con las palabras con que los nombra (en
                                         // "establecimiento", el campo donde ESTÁN ahora); [] si
                                         // corrige el último que anotó sin decir cuál
  "cambios": {                           // SOLO lo nuevo que dice el mensaje
    "texto": string | null,              // qué hay que hacer, si lo cambia
    "vence": "YYYY-MM-DD" | null,        // la fecha nueva
    "establecimiento": string | null,    // el campo nuevo
    "lote": string | null                // el lote nuevo, como en EVENTO
  }
}

PRECIO:
{
  "rubro": "granos" | "hacienda" | null,
  "producto": string | null     // en singular y minúscula, sin tildes: "soja", "maiz", "novillo"...
}""",
    reglas="""\
- Fechas relativas ("ayer", "el lunes", "la semana pasada") convertilas a YYYY-MM-DD usando la fecha de hoy.
  Si no se menciona fecha en un registro, usá la de hoy. En un pendiente la fecha suele ser futura
  ("el martes" es el próximo martes), pero si lo cuenta en pasado ("tenía que vacunar los terneros
  el lunes", "había que arreglar el alambrado ayer", "me olvidé de pedir los rollos el sábado") es
  esa fecha PASADA, la más reciente con ese día: el pendiente quedó vencido. Si no dice la fecha,
  "vence" es null.
- En consultas como "este mes" o "este año", completá "desde" y "hasta".
- NUNCA inventes datos. Si falta algo, null. Si el mensaje es ambiguo, confianza "baja".
- Las preguntas ("¿cuántas...?", "¿cuándo...?", "¿qué se le dio...?") son "consultar", no "registrar".
- El lote o potrero NO es el establecimiento: "lote 3" va en "lote"; "La Esperanza" en "establecimiento".""",
)
