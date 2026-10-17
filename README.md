# CampoBot · asistente de campo por WhatsApp 🐄

CampoBot (nombre provisorio) es un asistente **personal** por WhatsApp para anotar el trabajo en el campo y consultarlo después, en lenguaje natural y con audios.

> **Arquitectura y plan de desarrollo:** ver [`docs/arquitectura.md`](docs/arquitectura.md).

Cada número de WhatsApp tiene **su propio cuaderno privado**. Un veterinario que recorre cinco campos en el día anota todo en su cuaderno, y eso queda solo ahí: el dueño de cada campo no lo ve. Si el dueño quiere tenerlo, lo anota en su propio cuaderno.

```
vos> Estoy en La Esperanza
bot> 📍 Listo. Lo próximo que anotes lo guardo en La Esperanza.

vos> Vacuné 20 vacas contra aftosa en el lote 3
bot> ✅ Anotado en 📍 La Esperanza:
     • Vacunación (aftosa) · 20 vacas · lote 3 · 09/10/2026

vos> En El Ombú hice tacto a 50 vaquillonas
bot> ✅ Anotado en 📍 El Ombú:
     • Tacto · 50 vaquillonas · 09/10/2026

vos> ¿Qué hice hoy?
bot> 📋 *2 registros*
     • Tacto · 50 vaquillonas · 09/10/2026 · 📍 El Ombú
     • Vacunación (aftosa) · 20 vacas · lote 3 · 09/10/2026 · 📍 La Esperanza

vos> ¿A cuánto está la soja?
bot> • Soja (Rosario): *$ 560.000 por t* (ARS)
       Publicado el 08/10/2026
       Precios corrientes expresados en $/Tn por mercadería, entrega enseguida,
       pago contado, puesto sobre camión y/o vagón en zona Rosario. La fuente no
       aclara si incluye impuestos.
     Fuente: Cámara Arbitral de Cereales - Bolsa de Comercio de Rosario
     https://www.cac.bcr.com.ar/es/precios-de-pizarra

vos> ¿Me conviene vender ahora?
bot> Eso no lo puedo responder. Solo puedo: ...
```

## Qué hace

- **Registra eventos** de sanidad (vacunación, desparasitación, tratamientos), movimientos de hacienda (nacimientos, muertes, compras, ventas, traslados), pesadas, reproducción (tacto, servicio, destete) y del campo (lluvias, siembra, fumigación). Un mensaje puede traer varios eventos.
- **Todo se pide hablando normal**, por texto o audio: "che, ¿qué campos tengo cargados?", "¿quién ve lo que anoto?", "bueno, ¿qué podés hacer?". Los comandos escritos (`mis campos`, `mis datos`, `cambiar rubro`, `cambiar matrícula`, `privacidad`, `ayuda`, `borrar`, `cerrar sesión`, `borrar mis datos`) son atajos: si el mensaje es exactamente el comando responde sin IA; si no, la IA reconoce el pedido y responde lo mismo. Excepciones: borrar los datos exige escribir `confirmo borrar mis datos`, y los comandos del administrador solo funcionan escritos exactos. Las frases que tiene que reconocer, al menos 5 por función, están en `evaluacion/set.json`.
- **Varios pedidos en un mensaje**: "¿cuánto está la soja y el maíz?", o "anotá que llovieron 20 mm, borrá la cosecha del lote 5 y ¿la ivermectina está en SENASA?". La IA separa el mensaje en acciones (hasta 6) y el bot responde cada una en orden; los precios salen juntos, agrupados por fuente.
- **Corrige registros**: "a esas 5 vaquillonas las vacuné con ivermectina" o "no eran 20, eran 25" modifican el registro que corresponde (busca entre los últimos 20 el que coincide con lo que mencionás) en vez de crear uno nuevo, y muestra cómo quedó antes y ahora.
- **Borra registros puntuales**: "borrá la lluvia de La Pastora" o "borrá las 5 vaquillonas y la cosecha del lote 5, ambos de La Pastora". Cada descripción tiene que señalar un solo registro: si coincide con varios, no borra nada y muestra las opciones para que precises (o pedís borrar *todos*). Con "¿qué tengo anotado?" ves la lista.
- **Guarda en qué establecimiento y lote** fue cada cosa. Si no lo decís, usa el último establecimiento que nombraste y lo muestra en la confirmación. Los establecimientos y lotes son de tu cuenta: "Estancia La Esperanza" y "la esperanza" son el mismo, y el lote 3 de La Esperanza es distinto del lote 3 de El Ombú. `mis campos` los lista, con sus lotes y cuántos registros tiene cada uno.
- **Sesiones de trabajo**: "arranco manga en El Retiro lote 3" abre una sesión; lo que anotás sin decir el campo queda en ella, con su campo y su lote (la lluvia no hereda el lote). "terminamos" o `cerrar sesión` la cierra y muestra el resumen con los totales. Una abierta por persona: abrir otra cierra la anterior. Se cierra sola a las 12 horas sin mensajes, y el aviso con el resumen llega cuando volvés a escribir (el bot no manda nada por su cuenta).
- **Pendientes**: "tengo que revisar las aguadas el martes" lo anota como pendiente, con su fecha, en el campo que nombrás o, si no nombrás ninguno, en el de la sesión o el campo actual (sin cambiarlo). "¿qué tengo pendiente?" los lista con los vencidos primero (⚠️), también por campo; "ya está lo de las aguadas" lo marca hecho y "borrá el pendiente de las aguadas" lo saca. Si la descripción coincide con varios, no toca ninguno y muestra las opciones. Borrar 4 o más de una vez pide confirmación, como con los registros. El texto se guarda con hasta 120 caracteres y sin `*`, `_` ni `~`. `borrar` deshace lo último que anotaste, sea un registro o un pendiente.
- **Manda tus registros en PDF, Excel o CSV**: "mandame un PDF de lo que hice en La Pastora este mes" arma un PDF con la marca CampoBot (con los mismos filtros que una consulta) y te llega por WhatsApp como documento, para reenviarlo. "Excel" o "planilla" manda un `.xlsx` (hoja *Registros*, una columna por dato, lista para filtrar y sumar, y hoja *Resumen* con el membrete, los totales y el pie); el CSV solo si lo pedís, con `;` y BOM para que Excel lo abra bien. Un texto que parece una fórmula (`=…`) queda como texto. Lleva tu nombre, rubro, localidad y matrícula (si la cargaste), los totales, una fila por registro y al pie: "Registro de lo informado por el profesional. CampoBot es un auxiliar de cálculo y registro: no realiza recomendaciones ni reemplaza la prescripción profesional." En `python -m app chat` el archivo queda en la carpeta `archivos_chat/`.
- **Responde preguntas** sobre lo que anotaste vos (también por establecimiento). Los totales los calcula el código, no la IA, para que las sumas den bien.
- **Informa precios de referencia** de granos y hacienda de fuentes oficiales y mercados regulados, siempre con la fuente, la fecha de publicación, la moneda, si incluye impuestos u otros costos, y el link.
- **Verifica productos veterinarios en SENASA**: si un producto figura en el registro, con número, titular y estado. **No** informa precios de medicamentos ni de instrumental, ni dosis o indicaciones.
- **Entiende audios**: los transcribe con Whisper en Groq, con un glosario de palabras del campo según el rubro de cada persona (vaquillonas, caravana, ivermectina...).
- **La IA**: los mensajes los interpreta `openai/gpt-oss-120b` a través de **OpenRouter** (si está `OPENROUTER_API_KEY`), solo con servidores de retención cero (`zdr`) que no guardan ni entrenan con los datos (`data_collection: deny`) y que aceptan la salida en JSON (`require_parameters`). Si OpenRouter falla o no contesta en 12 s, responde **Groq** con el mismo modelo; sin la clave, todo va por Groq. Si ninguno atiende (límite de pedidos, sin saldo, sin respuesta), el bot contesta "⏳ Estoy con mucha demanda, probá de nuevo en un minuto". Un mensaje que la IA no pudo interpretar no cuenta para el límite diario. Cada pedido deja en el log quién respondió, los tokens, el costo y la demora (`IA openrouter (Cerebras): 4712 + 95 tokens, USD 0.000310, 0.9 s`), sin nada del mensaje.
- **Solo para personas invitadas**: quien escribe sin código de invitación recibe un mensaje fijo ("CampoBot está en prueba privada") y no se gasta IA ni se guarda nada.
- **Respuestas cortas sin IA**: el rubro se responde con el número o la palabra ("2", "agrónomo", "vete", "productor"), y los *sí* / *no* de una confirmación aceptan variantes comunes ("dale", "ok", "sí, borrá", "no, dejá", "mejor no"). Si la respuesta mezcla un sí y un no, o trae otra cosa ("no, borrá solo la de ayer"), no se toma como respuesta y sigue su camino normal.
- **Perfil por rubro**: nombre y apellido, rubro (veterinario, agrónomo o asesor, o productor) y localidad, con preguntas fijas al empezar. `mis datos` los muestra; `cambiar rubro` y `cambiar matrícula` los cambian.
  - `borrar`: deshace lo último que anotaste.
  - `ayuda`: muestra los ejemplos.

## Acceso: invitaciones y administradores

Los administradores se configuran con la variable `ADMIN_TELEFONOS` (números separados por coma, en el formato en que los manda WhatsApp: `549` + característica sin 0 + número sin 15). Siempre tienen acceso y, desde su WhatsApp, pueden:

- `invitar`: crea un código de invitación (`CAMPO-XXXX-XXXX`) y, si está `WA_NUMERO_BOT`, el link `wa.me` que abre el chat con el código ya escrito. Sirve para una sola persona y vence a los 7 días.
- `invitaciones`: lista los códigos vigentes y cuántas altas quedaron sin terminar.
- `anular CAMPO-XXXX-XXXX`: anula un código que todavía no se usó.
- `autorizar 5492494123456`: le da acceso a ese número directamente.
- `quitar 5492494123456`: le saca el acceso. Sus registros se conservan.
- `autorizados`: lista los números con acceso.

**Alta con código**: quien manda un código válido responde tres preguntas fijas, sin IA (nombre y apellido, rubro y localidad), y queda habilitado. El código queda atado a ese número, que tiene 7 días para terminar; después se borra lo que cargó y el código queda gastado. Después de 5 códigos equivocados en 24 horas, ningún código sirve desde ese número (sin avisarle); para contarlos se guarda el teléfono con HMAC (`CLAVE_HASH`), nunca el número.

Los usuarios que ya existían, y los que se autorizan con `autorizar`, responden las mismas preguntas la primera vez que escriben.

También desde la terminal: `python -m app usuarios autorizar 5492494123456` (o `quitar`, `lista`). El chat de prueba `python -m app chat` autoriza solo el número con el que chateás.

**Auditoría**: las altas, bajas, invitaciones, anulaciones y borrados quedan registrados solo con ids numéricos. Se ven con `python -m app auditoria`.

## Cómo funciona

```
WhatsApp ──► Meta Cloud API ──► POST /webhook (api/webhook.py)
                                   │  verifica la firma y responde 200 enseguida
                                   ▼
                  fila por número: de a un mensaje por persona, en orden
                                   ▼
                             audio? ──► Whisper (ia/) ──► texto
                                   ▼
           ¿número autorizado? ── no ──► "no tenés acceso" (sin IA)
                                   ▼
     atajos exactos, sin IA (borrar / ayuda / mis campos / autorizar...)
                                   ▼
       la IA SOLO clasifica ──► JSON con acciones ──► se valida con el esquema de cada acción
                                   │                     (lo que no valida: fuera de alcance)
                                   ▼
        registro de acciones: registrar | corregir | borrar | consultar | precio | ...
                                   ▼
          cada manejador usa el cuaderno de la persona y arma la respuesta con textos fijos
```

### Estructura del código

| Carpeta | Qué tiene |
|---|---|
| `app/api/` | Rutas web finas: webhook de WhatsApp (firma, deduplicación, audios, orden), salud y `/privacidad` |
| `app/canales/` | WhatsApp: lectura del webhook, envío de mensajes, descarga de audios, firma |
| `app/nucleo/` | El camino del mensaje (`pipeline.py`), acceso, comandos fijos, charla reciente, registro de acciones y el `Cuaderno`: la única puerta a los datos de cada persona |
| `app/ia/` | Los proveedores de IA detrás de una interfaz (OpenRouter, con Groq de respaldo y para los audios), el armado del prompt, los tipos que validan su salida y el set de evaluación (`evaluacion.py`) |
| `app/modulos/comun/` | Las acciones: registrar, corregir, borrar, consultar, establecimiento, sesiones, pendientes, lo de la cuenta (ayuda, privacidad, mis campos, mis datos, cambiar rubro y matrícula, borrar mis datos), saludo/aclarar, precios y SENASA. Cada una con su esquema y su manejador; lo que el módulo le suma al prompt está en `prompt.py` y su glosario para Whisper en `glosario.py` |
| `app/fuentes/` | Descarga y carga de precios oficiales y del registro de SENASA |
| `app/salidas/` | Formato de los mensajes de WhatsApp y la página de privacidad |
| `app/infra/` | Configuración, base de datos, modelos, migraciones (Alembic), logs y la fila por número |
| `app/terminal.py` | Los comandos `python -m app ...` |

**Para sumar una acción**: un archivo en el módulo con su esquema (qué puede devolver la IA), su manejador (qué hace el código) y `ACCION = Accion("intencion", Esquema, manejar)`; se agrega a `ACCIONES` del módulo y se describe en la parte del prompt del módulo (`prompt.py`: la intención, sus campos, qué es y sus reglas). El núcleo no se toca.

**Tope del prompt**: el prompt de cada rubro tiene como mucho `LARGO_MAXIMO_PROMPT` caracteres (24.000; hoy son unos 16.600) y un test lo verifica: cada carácter de más se paga y se espera en cada mensaje.

**Prompt por perfil**: cada persona recibe un prompt armado con los módulos de su rubro (`MODULOS_POR_RUBRO` en `app/modulos/__init__.py`): el común lo tienen todos; ganadería (veterinario y productor) y agricultura (agrónomo y productor) se suman cuando existan. Si la IA devuelve una acción de un módulo que la persona no tiene, se trata como fuera de alcance. Los audios se transcriben con el glosario de esos mismos módulos (las palabras que Whisper suele escribir mal), que entra en el `prompt` de Whisper: hasta 500 caracteres por rubro, y un test lo verifica.

## Alcance estricto y seguridad

El bot no es un chat de IA. Está armado para que no se pueda usar para otra cosa:

- **La IA solo clasifica.** Devuelve un JSON con la intención y los datos. Ningún texto escrito por la IA llega al usuario: todas las respuestas se arman en el código con plantillas fijas. Por eso no puede dar recomendaciones, inventar datos ni conversar de otros temas, aunque se lo pidan.
- **La IA no consulta la base de datos.** Recibe el mensaje y, como contexto, los últimos mensajes de esa misma persona con el bot (de los últimos 30 minutos, tabla `mensajes_chat`), para entender respuestas cortas como "sí", "la de ayer" o "La Pastora" después de una pregunta. Nunca ve lo de otras personas.
- **Interpreta con flexibilidad, pero sin salirse del tema.** Si el mensaje tiene que ver con el trabajo en el campo, los registros, precios o SENASA, la IA busca la interpretación más razonable; si falta un dato imprescindible, el bot repregunta con preguntas fijas ("¿En qué establecimiento fue?"). Saludos y agradecimientos tienen una respuesta corta. Solo rechaza recomendaciones, temas ajenos e intentos de manipularla.
- **Todo lo demás es "fuera de alcance"**: consejos ("¿conviene vender?"), preguntas generales, pedidos de textos o código, datos de otras personas, intentos de cambiarle las instrucciones. A todo eso responde con un mensaje fijo.
- **Lo que devuelve la IA se valida:** cada acción tiene un esquema (Pydantic). Los datos se limpian (textos recortados, números y fechas convertidos) y lo que no entra en el esquema se descarta.
- **Datos aislados por persona:** la IA nunca escribe SQL, solo filtros. Todo acceso a los datos de una persona pasa por una sola capa (`app/nucleo/cuaderno.py`) que filtra por su usuario; un test verifica que ningún otro módulo lo haga a mano.
- **Límites de uso** (configurables con variables de entorno): `MAX_LARGO_MENSAJE` (800 caracteres), `MAX_AUDIO_BYTES` (~3-4 min de audio) y `LIMITE_DIARIO_IA` (80 mensajes por usuario y por día).
- Los números no autorizados no llegan a la IA: no se transcriben sus audios ni se interpretan sus mensajes.
- **Firma de Meta obligatoria**: el webhook valida `X-Hub-Signature-256`. Con `ENTORNO=produccion` (el valor si no se define) el servidor no arranca sin `META_APP_SECRET`, `WA_VERIFY_TOKEN`, `WA_TOKEN`, `WA_PHONE_NUMBER_ID`, `GROQ_API_KEY` y `CLAVE_HASH`, y el error dice cuáles faltan. Si `META_APP_SECRET` está definido, la firma se valida siempre, también en desarrollo; solo con `ENTORNO=desarrollo` y sin secreto se acepta sin firma, para probar en tu compu.
- **Mensajes en orden**: los de una misma persona se procesan de a uno y en el orden en que los escribió (por ejemplo, "borrá todo" y después "sí"). Los reintentos de Meta se descartan por su id.
- **Logs sin datos personales**: los números salen enmascarados (`549*******456`), también en los logs de uvicorn, y no se loguean el texto de los mensajes ni su id de WhatsApp (que lleva el número). Los errores de la base no muestran los valores de la consulta, los de la IA solo dicen el tipo y el código, y el access log no muestra el query string (el `GET /webhook` de Meta trae el token de verificación).
- **Ids de mensajes por 7 días**: para descartar los reintentos de Meta se guarda el id de cada mensaje recibido; a los 7 días se borra.

## Privacidad y datos personales

- **Política de privacidad**: el bot la publica en `/privacidad` (por ejemplo `https://tu-bot.up.railway.app/privacidad`). Esa es la URL que pide Meta para publicar la app. Completá `PRIVACIDAD_RESPONSABLE` (nombre o razón social) y `PRIVACIDAD_CONTACTO` (email) en el `.env`. El texto está en `app/salidas/privacidad.py` y es un **borrador**: revisalo con alguien que sepa de protección de datos (Ley 25.326) antes de tener clientes.
- **`privacidad`**: el usuario recibe un resumen de cómo se usan sus datos y, si está configurada `PRIVACIDAD_URL`, el link a la política completa.
- **`borrar mis datos`**: el bot muestra qué se va a borrar y pide confirmar con `confirmo borrar mis datos`. Al confirmar se eliminan el cuaderno, los mensajes recientes, el uso diario y el número de la persona, que pierde el acceso hasta que el administrador la habilite de nuevo. El aviso también sale pidiéndolo con otras palabras ("dame de baja"), pero la confirmación es solo escrita y exacta: nunca pasa por la IA.

## Precios de fuentes oficiales

Los precios **no** los busca la IA en internet: los descarga un proceso aparte desde fuentes registradas en `app/fuentes/precios.py`, los guarda en la tabla `cotizaciones` y el bot responde solo con eso, siempre con la fuente, la fecha y el link. Si un dato tiene más de `DIAS_PRECIO_VIGENTE` días (7 por defecto), avisa que no está actualizado. Si no hay datos, lo dice y no inventa.

Solo se aceptan links `https` de dominios oficiales o de mercados regulados (`DOMINIOS_OFICIALES`): `*.gob.ar` (Secretaría de Agricultura, SENASA, INTA), Bolsa de Comercio de Rosario, Mercado Agroganadero de Cañuelas, Matba Rofex / A3, Bolsa de Cereales de Buenos Aires y Bolsa de Cereales de Bahía Blanca.

```bat
python -m app precios actualizar
python -m app precios cargar precios.csv
python -m app precios ver soja
```

- `actualizar` corre todas las fuentes de `FUENTES`.
- `cargar` carga precios a mano desde un CSV (columnas abajo).
- `ver` muestra lo que respondería el bot.

Columnas del CSV: `fuente,url,rubro,producto,plaza,valor,moneda,unidad,fecha,incluye_impuestos,costos_adicionales`.
`moneda` es `ARS` (por defecto) o `USD`, tal como publica la fuente: el bot no convierte monedas. `fecha` es la fecha de publicación que informa la fuente. `incluye_impuestos` es `si`, `no` o vacío; si está vacío y no hay `costos_adicionales`, el bot aclara que la fuente no lo informa.

En Railway, `actualizar` se programa como **Cron Job** (por ejemplo, de lunes a viernes a las 18:30).

Fuentes registradas en `FUENTES`:

| Fuente | Qué trae | Cómo |
|---|---|---|
| Cámara Arbitral de Cereales (Bolsa de Comercio de Rosario) | Pizarra de trigo, maíz, girasol, soja y sorgo en $/t, plaza Rosario | Lee los paneles de [precios de pizarra](https://www.cac.bcr.com.ar/es/precios-de-pizarra). Si un grano está S/C (sin cotización) y la Cámara publica un estimado, se guarda avisando que es estimado; si no hay ni estimado, ese grano no se guarda. El valor en dólares no se usa: la propia página aclara que es "sólo a título informativo" |
| Mercado Agroganadero de Cañuelas | Promedio por kg vivo de novillos, novillitos, vaquillonas, vacas, toros y MEJ | Pide la planilla de una rueda por POST. Los días sin operaciones vienen vacíos, así que prueba día por día hacia atrás hasta la última rueda. Verifica cada promedio contra el importe y los kilos de la categoría: si no cierran, falla en lugar de guardar |

Las dos guardan la **fecha de publicación que informa la fuente** (no la de hoy) y, en `costos_adicionales`, solo lo que la fuente aclara. Ninguna de las dos dice si sus precios incluyen impuestos, así que el bot lo aclara como no informado en lugar de suponerlo.

Los lectores separan la descarga (`obtener`) de la lectura del HTML (`leer`), y los tests de `tests/test_precios.py` corren `leer` contra los HTML guardados en `tests/fixtures/`, sin tocar internet.

## Productos veterinarios (SENASA)

El bot solo verifica si un producto está en el **registro oficial de SENASA** (Vademécum de Productos Veterinarios): número de registro, titular, principio activo y estado, con la fecha de los datos y el link. No informa precios, dosis ni indicaciones. Si un producto no aparece, lo aclara y no lo da por "no registrado".

```bat
python -m app senasa actualizar
python -m app senasa cargar registro.csv --fecha 2026-10-10 --url https://www.argentina.gob.ar/senasa/...
python -m app senasa ver ivermectina
```

- `actualizar` descarga la consulta pública de SENASA.
- `cargar` reemplaza el registro con un CSV, con la fecha de los datos y la página oficial de donde salen.
- `ver` muestra lo que respondería el bot.

Columnas del CSV: `nombre,registro,titular,principio_activo,estado`. Cada carga reemplaza el registro entero. Solo acepta links `https` de `*.gob.ar`.

`actualizar` trae los productos de la **Consulta Pública de Productos Veterinarios** del sistema ADT de SENASA, que es pública y no pide clave fiscal. Son unos 8.400 productos. Tres cosas a tener en cuenta:

- El botón "Exportar a CSV" de SENASA devuelve en realidad un **Excel 97-2003** con nombre `.csv`; por eso el proyecto depende de `xlrd`.
- La consulta pública publica certificado, nombre comercial, expediente y firma, pero **no** el principio activo ni el estado del registro. Esos campos quedan vacíos y el bot muestra "no informado" en lugar de inventarlos. La búsqueda, entonces, es por nombre comercial: "ivermectina" encuentra los 26 productos que la llevan en el nombre.
- SENASA **no informa a qué fecha están los datos**, así que se guarda la fecha de la descarga, que es lo que el bot muestra como "datos al ...".

El Vademécum nuevo (`aps2.senasa.gov.ar/vademecumVet`) sí tiene principio activo e indicaciones, pero su API está detrás del SSO de SENASA: todo `/api/...` redirige al login, así que no se puede leer sin credenciales.

Como `DOMINIOS_OFICIALES` solo acepta `*.gob.ar` para SENASA y la consulta vive en `aps2.senasa.gov.ar`, el registro se guarda con la URL de la página oficial de [Listados Oficiales](https://www.argentina.gob.ar/senasa/programas-sanitarios/productos-veterinarios-fitosanitarios-y-fertilizantes/listados-oficiales), que es desde donde una persona llega a esa misma consulta.

## Probarlo en tu compu

Los comandos son para la terminal de Windows (cmd), desde la carpeta del proyecto:

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```

Completá en `.env` al menos `GROQ_API_KEY` y dejá `ENTORNO=desarrollo`. Después:

```bat
python -m app db migrar
python -m app chat
```

`db migrar` crea la base (`campo.db`, SQLite) o la pone al día. `chat` abre un chat por terminal con el bot, sin WhatsApp.

### Set de evaluación contra la IA real

`python -m app eval` manda las frases de `evaluacion/set.json` a la IA y compara las intenciones que devuelve con las esperadas. Cuesta plata (con OpenRouter, el set entero sale unos centavos de dólar): correlo cuando cambia el prompt o un esquema.

```bat
python -m app eval --funcion ayuda --funcion mis_campos
python -m app eval --desde 20 --limite 10
python -m app eval --esfuerzo low --tope-usd 0.20
python -m app eval --proveedor groq --limite 5 --pausa 60
```

- Por defecto usa OpenRouter si está `OPENROUTER_API_KEY` (si no, Groq), sin respaldo, con el prompt de un productor (`--rubro`).
- Muestra cada frase (✓ o ✗, demora y tokens) y al final la precisión, las llamadas, los tokens, el costo y la demora (mediana y p95).
- Frena si el costo llega al tope (`--tope-usd`, USD 0,50 por defecto). Groq no informa el costo: con Groq no hay tope por costo, y en el plan gratuito conviene `--pausa 60` y pocas frases.

### Probar con el celular (ngrok)

1. En `.env`: `ENTORNO=desarrollo`, `GROQ_API_KEY`, `WA_TOKEN`, `WA_PHONE_NUMBER_ID`, `WA_VERIFY_TOKEN`, `META_APP_SECRET` y tu número en `ADMIN_TELEFONOS`. Para probar invitaciones, también `CLAVE_HASH` y `WA_NUMERO_BOT`. Con `META_APP_SECRET` puesto, la firma de Meta se valida igual que en producción.
2. Terminal 1: `uvicorn app.main:app --port 8000`
3. Terminal 2: `ngrok http --domain=MI-DOMINIO 8000`, con el dominio fijo gratuito que te da ngrok (en su panel, *Domains*; por ejemplo `algo-algo.ngrok-free.app`). Así la URL es siempre la misma.
4. En Meta → *Casos de uso → Conectar en WhatsApp → Personalizar* → *Configuración* (*Configuration*), sección *Webhook*: Callback URL `https://MI-DOMINIO/webhook`, Verify token el de `WA_VERIFY_TOKEN`, y suscripción a **messages**. Con el dominio fijo esto se hace una sola vez. (Si usás `ngrok http 8000` sin dominio, la URL cambia cada vez que lo abrís y hay que actualizarla en Meta.)
5. Mandale `ayuda` al número de prueba desde tu celular. En la terminal 1 ves los logs (con los teléfonos enmascarados).

### Antes de subir cambios

```bat
ruff check .
ruff format .
mypy
pytest
```

Son los mismos chequeos que corre GitHub Actions en cada push (`.github/workflows/ci.yml`). Los tests no usan la IA real ni internet.

El CI corre además las migraciones y los tests sobre **Postgres**, como en producción. Los tests usan SQLite salvo que definas `TEST_DATABASE_URL` con una base de Postgres que sea **solo para eso**, porque los tests borran todas sus tablas:

```bat
set TEST_DATABASE_URL=postgresql://usuario:clave@localhost:5432/campo_test
pytest
```

## Base de datos y migraciones

Las tablas se crean y cambian con migraciones de **Alembic** (`app/infra/migraciones/`), así los datos sobreviven a cada cambio. La base la cambia **solo** `python -m app db migrar`: el servidor y los demás comandos revisan que esté al día y, si falta migrar, avisan y no arrancan. En Railway no hay que hacer nada: el `Dockerfile` corre `db migrar` antes de arrancar el bot en cada deploy. En tu compu, después de un `git pull` que traiga migraciones:

```bat
python -m app db estado
python -m app db migrar
```

- **Base vacía**: se crea con todas las migraciones.
- **Base creada antes de Alembic** (con versiones anteriores del bot): se compara con la migración base (`0001`), que es el esquema que tenían esas bases, y no con los modelos actuales. Si coincide, se marca como en esa versión sin tocar los datos (es lo que hace `alembic stamp`) y después se aplican las migraciones siguientes. Si solo le faltan tablas enteras (de funciones que se sumaron después), se crean. Si difiere en otra cosa, no se toca nada y `db migrar` explica qué difiere. Antes de migrar una base con datos, hacé una copia: `copy campo.db campo.db.bak`.
- **Cambiar una tabla**: modificá `app/infra/modelos.py` y generá la migración con `alembic revision --autogenerate -m "qué cambia"`. Revisala, probala con `python -m app db migrar` y subila junto con el cambio. La `0001` no se toca nunca: define el esquema de partida y se usa para reconocer las bases viejas.
- **Nombres de los constraints**: claves primarias, foráneas y únicas siguen la convención de `app/infra/db.py`, que es la misma que usa Postgres por defecto (`usuarios_pkey`, `eventos_usuario_id_fkey`, `uso_diario_usuario_id_fecha_key`). Una migración se puede referir a ellos por nombre en cualquier base. La `0002` se los puso a las bases SQLite, que los tenían sin nombre; en Postgres no cambió nada.

## Ponerlo en producción (Railway + Postgres)

En Railway el proyecto queda armado con **tres servicios**, todos dentro del mismo proyecto:

```
┌──────────────────────── Proyecto en Railway ────────────────────────┐
│                                                                     │
│  [ bot ]  ← Meta llama a https://tu-bot.up.railway.app/webhook      │
│   Dockerfile · prendido siempre · se redeploya con cada push        │
│      │ lee y escribe                                                │
│      ▼                                                              │
│  [ Postgres ]  base administrada, con backups                       │
│      ▲                                                              │
│      │ carga precios y SENASA                                       │
│  [ actualizar-precios ]  cron: lunes a viernes 18:30 (Argentina)    │
│   corre, actualiza y se apaga                                       │
└─────────────────────────────────────────────────────────────────────┘
```

| Servicio | Qué es | Configuración |
|---|---|---|
| **bot** | El servidor (`app/main.py`) | Rama del repo · variables de `.env.example` · `DATABASE_URL=${{Postgres.DATABASE_URL}}` · dominio público |
| **Postgres** | La base de datos | Se crea con *New → Database → PostgreSQL* · activar *Backups* |
| **actualizar-precios** | Mismo repo, otro comando | Start command `sh -c "python -m app precios actualizar && python -m app senasa actualizar"` · Cron `30 21 * * 1-5` (UTC) · solo `DATABASE_URL` · sin dominio |

### Paso a paso

1. Entrá a [railway.com](https://railway.com) con tu cuenta de GitHub → *New Project* → *Deploy from GitHub repo* → este repo. En *Settings → Source → Branch* elegí la rama del bot.
2. *New → Database → PostgreSQL*.
3. En el servicio del bot → *Variables* → *Raw Editor*: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `ENTORNO=produccion` y el resto de las variables de `.env.example` (`GROQ_API_KEY`, `OPENROUTER_API_KEY`, `WA_TOKEN`, `WA_PHONE_NUMBER_ID`, `META_APP_SECRET`, `WA_VERIFY_TOKEN`, `ADMIN_TELEFONOS`, `CLAVE_HASH`, `WA_NUMERO_BOT`, `PRIVACIDAD_*`). Si falta alguna obligatoria, el deploy falla y el log dice cuál.
4. *Settings → Networking → Generate Domain*. Abrí `https://tu-bot.up.railway.app/`: tiene que responder `{"ok": true}`.
5. Creá el servicio **actualizar-precios** (*New → GitHub Repo*, mismo repo y rama) con el start command y el cron de la tabla, y la variable `DATABASE_URL`. Ejecutalo una vez a mano para cargar los datos iniciales.
6. En Meta → *Casos de uso → Conectar en WhatsApp → Personalizar* → *Configuración* (*Configuration*), sección *Webhook*: Callback URL `https://tu-bot.up.railway.app/webhook`, el mismo verify token, y suscripción a **messages**. La política de privacidad queda en `https://tu-bot.up.railway.app/privacidad`.
7. Mandale `hola` al bot. Los logs se ven en el servicio del bot → *Deployments* → *View logs*.

### Uso diario

- **Subir cambios**: hacés `git push` a la rama y Railway vuelve a construir y prender el bot solo. Si el cambio trae una migración, se aplica al arrancar (`python -m app db migrar`, en el `Dockerfile`).
- **Cambiar una clave** (por ejemplo, el token de Meta): editás la variable en *Variables* y se redeploya solo.
- **La IA**: con `OPENROUTER_API_KEY` en *Variables*, OpenRouter interpreta los mensajes y Groq queda de respaldo; sin ella, todo va por Groq (no es obligatoria: el bot arranca igual). Al arrancar, el log dice cuál se usa (`IA: OpenRouter (openai/gpt-oss-120b, esfuerzo medium) con Groq de respaldo; audios en Groq`), y cada mensaje deja una línea `IA openrouter (...)` o `IA groq`. El saldo y los pedidos se ven en [openrouter.ai/activity](https://openrouter.ai/activity). `OPENROUTER_ESFUERZO` (low, medium o high) cambia cuánto razona el modelo.
- **Ver qué pasa**: *View logs* del bot muestra lo mismo que la terminal de uvicorn.
- **Copias de la base**: Postgres → *Backups*, o `pg_dump` con la `DATABASE_URL`.
- **Costo**: plan Hobby, alrededor de USD 5 por mes para este tamaño (revisá el precio vigente).

### Dónde está cada dato en Meta

- WhatsApp está en el panel de la app, en *Casos de uso → Conectar en WhatsApp → Personalizar*. Ahí están las pantallas *Configuración de la API* (*API Setup*) y *Configuración* (*Configuration*, la del webhook).
- `WA_TOKEN` y `WA_PHONE_NUMBER_ID`: en *Configuración de la API*. En la misma pantalla figura el identificador de la **cuenta** de WhatsApp Business (*WhatsApp Business Account ID*), que no es el del número. El token temporal vence cada 24 h. Para producción, creá un **System User** en Business Settings y generá un token permanente con los permisos `whatsapp_business_messaging` y `whatsapp_business_management`.
- `META_APP_SECRET`: en *Configuración de la app → Básica → Clave secreta de la app* (*App settings → Basic → App secret*).

### Problemas comunes

- **El bot recibe pero no contesta, y en los logs aparece el error `131030` ("Recipient phone number not in allowed list")**: con el número de prueba de Meta tenés que agregar cada destinatario en *Configuración de la API*, en el campo *Para* (*To*). Si ya está agregado y sigue fallando con un número argentino, poné `WA_AR_QUITAR_9=true`: Meta recibe el número como `549…` pero a veces lo espera como `54…`.
- **No llega nada al webhook**: revisá que esté suscripto a `messages` y que la URL termine en `/webhook`.
- **El botón *Probar* (*Test*) del webhook llega, pero los mensajes reales no**: falta conectar la cuenta de WhatsApp Business a la app. Se hace una sola vez, desde cmd:

  ```bat
  curl -X POST "https://graph.facebook.com/v21.0/ID_DE_LA_CUENTA/subscribed_apps" -H "Authorization: Bearer TOKEN"
  ```

  `ID_DE_LA_CUENTA` es el identificador de la **cuenta** de WhatsApp Business (está en *Configuración de la API*), no el del número (`WA_PHONE_NUMBER_ID`). `TOKEN` es tu `WA_TOKEN`. Tiene que responder `{"success":true}`.

## Próximos pasos posibles

El plan por etapas está en [`docs/arquitectura.md`](docs/arquitectura.md). Además:

- Stock por lote calculado a partir de nacimientos, muertes, compras, ventas y traslados.
- Recordatorios, por ejemplo: "en 21 días toca la segunda dosis".
- Exportar a Excel y un panel web para el dueño.
