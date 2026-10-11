# Asistente de campo por WhatsApp 🐄

Asistente **personal** por WhatsApp para anotar el trabajo en el campo y consultarlo después, en lenguaje natural y con audios.

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
- **Corrige registros**: "a esas 5 vaquillonas las vacuné con ivermectina" o "no eran 20, eran 25" modifican el registro que corresponde (busca entre los últimos 20 el que coincide con lo que mencionás) en vez de crear uno nuevo, y muestra cómo quedó antes y ahora.
- **Borra registros puntuales**: "borrá la lluvia de La Pastora" o "borrá las 5 vaquillonas y la cosecha del lote 5, ambos de La Pastora". Cada descripción tiene que señalar un solo registro: si coincide con varios, no borra nada y muestra las opciones para que precises (o pedís borrar *todos*). Con "¿qué tengo anotado?" ves la lista.
- **Guarda en qué establecimiento** fue cada cosa. Si no lo decís, usa el último que nombraste y lo muestra en la confirmación.
- **Responde preguntas** sobre lo que anotaste vos (también por establecimiento). Los totales los calcula el código, no la IA, para que las sumas den bien.
- **Informa precios de referencia** de granos y hacienda de fuentes oficiales y mercados regulados, siempre con la fuente, la fecha de publicación, la moneda, si incluye impuestos u otros costos, y el link.
- **Verifica productos veterinarios en SENASA**: si un producto figura en el registro, con número, titular y estado. **No** informa precios de medicamentos ni de instrumental, ni dosis o indicaciones.
- **Entiende audios**: los transcribe con Whisper en Groq.
- **Solo para números autorizados**: un desconocido que escribe recibe "no tenés acceso" y no se gasta IA ni se guarda nada.
  - `borrar`: deshace lo último que anotaste.
  - `ayuda`: muestra los ejemplos.

## Acceso (números autorizados)

Los administradores se configuran con la variable `ADMIN_TELEFONOS` (números separados por coma, en el formato en que los manda WhatsApp: `549` + característica sin 0 + número sin 15). Siempre tienen acceso y, desde su WhatsApp, pueden:

- `autorizar 5492494123456`: le da acceso a ese número.
- `quitar 5492494123456`: le saca el acceso. Sus registros se conservan.
- `autorizados`: lista los números con acceso.

También desde la terminal: `python -m app.usuarios autorizar 5492494123456` (o `quitar`, `lista`). El chat de prueba `python -m app.cli` autoriza solo el número con el que chateás.

## Cómo funciona

```
WhatsApp ──► Meta Cloud API ──► POST /webhook (FastAPI)
                                   │  verifica la firma y responde 200 enseguida
                                   ▼
                             audio? ──► Whisper (Groq) ──► texto
                                   ▼
           ¿número autorizado? ── no ──► "no tenés acceso" (sin IA)
                                   ▼
                  comandos (borrar / ayuda / autorizar...)
                                   ▼
   el modelo (Groq) SOLO clasifica: registrar | consultar | establecimiento | precio | ... | fuera_de_alcance
                │                     │                         │                │
       guarda Evento(s)     filtros ──► busca SOLO en   último precio de   mensaje fijo
                            el cuaderno del usuario     tabla cotizaciones
                                   ▼                          ▼
                     la respuesta la arma el código, con plantillas fijas
```

| Archivo | Qué tiene |
|---|---|
| `app/main.py` | Webhook de WhatsApp: verificación, firma, deduplicación de reintentos y audios |
| `app/bot.py` | Lógica del asistente: comandos, registrar, consultar, borrar |
| `app/llm.py` | Prompt del clasificador y llamadas a Groq (interpretar, transcribir) |
| `app/precios.py` | Fuentes oficiales de precios, carga y respuesta con fuente y fecha |
| `app/senasa.py` | Registro de productos veterinarios de SENASA: carga y verificación |
| `app/consultas.py` | Búsqueda con filtros y totales precalculados |
| `app/models.py` | Tablas: `usuarios`, `eventos`, `cotizaciones`, `productos_veterinarios`, `uso_diario`, `mensajes_procesados` |
| `app/whatsapp.py` | Envío de mensajes y descarga de audios desde Meta |
| `app/cli.py` | Chat por terminal para probar sin WhatsApp |

## Alcance estricto y seguridad

El bot no es un chat de IA. Está armado para que no se pueda usar para otra cosa:

- **La IA solo clasifica.** Devuelve un JSON con la intención y los datos. Ningún texto escrito por la IA llega al usuario: todas las respuestas se arman en el código con plantillas fijas. Por eso no puede dar recomendaciones, inventar datos ni conversar de otros temas, aunque se lo pidan.
- **La IA no consulta la base de datos.** Recibe el mensaje y, como contexto, los últimos mensajes de esa misma persona con el bot (de los últimos 30 minutos, tabla `mensajes_chat`), para entender respuestas cortas como "sí", "la de ayer" o "La Pastora" después de una pregunta. Nunca ve lo de otras personas.
- **Interpreta con flexibilidad, pero sin salirse del tema.** Si el mensaje tiene que ver con el trabajo en el campo, los registros, precios o SENASA, la IA busca la interpretación más razonable; si falta un dato imprescindible, el bot repregunta con preguntas fijas ("¿En qué establecimiento fue?"). Saludos y agradecimientos tienen una respuesta corta. Solo rechaza recomendaciones, temas ajenos e intentos de manipularla.
- **Todo lo demás es "fuera de alcance"**: consejos ("¿conviene vender?"), preguntas generales, pedidos de textos o código, datos de otras personas, intentos de cambiarle las instrucciones. A todo eso responde con un mensaje fijo.
- **Búsquedas aisladas por campo:** la IA nunca escribe SQL, solo filtros, y toda búsqueda se limita a los registros de quien pregunta.
- **Límites de uso** (configurables con variables de entorno): `MAX_LARGO_MENSAJE` (800 caracteres), `MAX_AUDIO_BYTES` (~3-4 min de audio) y `LIMITE_DIARIO_IA` (80 mensajes por usuario y por día).
- Los números no autorizados no llegan a la IA: no se transcriben sus audios ni se interpretan sus mensajes.
- El webhook valida la firma `X-Hub-Signature-256` de Meta.

## Precios de fuentes oficiales

Los precios **no** los busca la IA en internet: los descarga un proceso aparte desde fuentes registradas en `app/precios.py`, los guarda en la tabla `cotizaciones` y el bot responde solo con eso, siempre con la fuente, la fecha y el link. Si un dato tiene más de `DIAS_PRECIO_VIGENTE` días (7 por defecto), avisa que no está actualizado. Si no hay datos, lo dice y no inventa.

Solo se aceptan links `https` de dominios oficiales o de mercados regulados (`DOMINIOS_OFICIALES`): `*.gob.ar` (Secretaría de Agricultura, SENASA, INTA), Bolsa de Comercio de Rosario, Mercado Agroganadero de Cañuelas, Matba Rofex / A3, Bolsa de Cereales de Buenos Aires y Bolsa de Cereales de Bahía Blanca.

```bash
python -m app.precios actualizar        # corre todas las fuentes de FUENTES
python -m app.precios cargar precios.csv # carga manual (columnas abajo)
python -m app.precios ver soja          # muestra lo que respondería el bot
```

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

```bash
python -m app.senasa actualizar     # descarga la consulta pública de SENASA
python -m app.senasa cargar registro.csv --fecha 2026-10-10 --url https://www.argentina.gob.ar/senasa/...
python -m app.senasa ver ivermectina
```

Columnas del CSV: `nombre,registro,titular,principio_activo,estado`. Cada carga reemplaza el registro entero. Solo acepta links `https` de `*.gob.ar`.

`actualizar` trae los productos de la **Consulta Pública de Productos Veterinarios** del sistema ADT de SENASA, que es pública y no pide clave fiscal. Son unos 8.400 productos. Tres cosas a tener en cuenta:

- El botón "Exportar a CSV" de SENASA devuelve en realidad un **Excel 97-2003** con nombre `.csv`; por eso el proyecto depende de `xlrd`.
- La consulta pública publica certificado, nombre comercial, expediente y firma, pero **no** el principio activo ni el estado del registro. Esos campos quedan vacíos y el bot muestra "no informado" en lugar de inventarlos. La búsqueda, entonces, es por nombre comercial: "ivermectina" encuentra los 26 productos que la llevan en el nombre.
- SENASA **no informa a qué fecha están los datos**, así que se guarda la fecha de la descarga, que es lo que el bot muestra como "datos al ...".

El Vademécum nuevo (`aps2.senasa.gov.ar/vademecumVet`) sí tiene principio activo e indicaciones, pero su API está detrás del SSO de SENASA: todo `/api/...` redirige al login, así que no se puede leer sin credenciales.

Como `DOMINIOS_OFICIALES` solo acepta `*.gob.ar` para SENASA y la consulta vive en `aps2.senasa.gov.ar`, el registro se guarda con la URL de la página oficial de [Listados Oficiales](https://www.argentina.gob.ar/senasa/programas-sanitarios/productos-veterinarios-fitosanitarios-y-fertilizantes/listados-oficiales), que es desde donde una persona llega a esa misma consulta.

## Probarlo en tu compu

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # completá al menos GROQ_API_KEY
python -m app.cli           # chat por terminal, usa SQLite
pytest                      # tests (no usan la IA real)
```

## Ponerlo en producción (Railway + Postgres)

1. **Railway**: entrá a [railway.app](https://railway.app), creá un proyecto con *Deploy from GitHub repo* y elegí este repo. Detecta el `Dockerfile` solo.
2. Dentro del proyecto, agregá una base: *New → Database → PostgreSQL*. En el servicio del bot, agregá la variable `DATABASE_URL` con el valor `${{Postgres.DATABASE_URL}}`.
3. Cargá las demás variables de `.env.example` en *Variables*.
4. En *Settings → Networking → Generate Domain* vas a obtener una URL tipo `https://campo-bot.up.railway.app`.
5. **Meta**: entrá a [developers.facebook.com](https://developers.facebook.com) → tu app → *WhatsApp → Configuration → Webhook*:
   - Callback URL: `https://TU-DOMINIO/webhook`
   - Verify token: el mismo valor que pusiste en `WA_VERIFY_TOKEN`
   - Suscribite al campo **messages**.
6. Mandale `hola` al número del bot.

### Dónde está cada dato en Meta

- `WA_TOKEN` y `WA_PHONE_NUMBER_ID`: en *WhatsApp → API Setup*. El token temporal vence cada 24 h. Para producción, creá un **System User** en Business Settings y generá un token permanente con los permisos `whatsapp_business_messaging` y `whatsapp_business_management`.
- `META_APP_SECRET`: en *App settings → Basic → App secret*.

### Problemas comunes

- **El bot recibe pero no contesta, y en los logs aparece el error `131030` ("Recipient phone number not in allowed list")**: con el número de prueba de Meta tenés que agregar cada destinatario en *API Setup → To*. Si ya está agregado y sigue fallando con un número argentino, poné `WA_AR_QUITAR_9=true`: Meta recibe el número como `549…` pero a veces lo espera como `54…`.
- **No llega nada al webhook**: revisá que esté suscripto a `messages` y que la URL termine en `/webhook`.

## Próximos pasos posibles

- Migraciones con Alembic, cuando haya que cambiar tablas con datos reales.
- Stock por lote calculado a partir de nacimientos, muertes, compras, ventas y traslados.
- Recordatorios, por ejemplo: "en 21 días toca la segunda dosis".
- Exportar a Excel y un panel web para el dueño.
