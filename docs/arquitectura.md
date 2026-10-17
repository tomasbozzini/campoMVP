# Arquitectura y plan de desarrollo

Documento de referencia del proyecto: qué construimos, cómo está organizado el código, qué
decisiones tomamos y en qué orden avanzamos. Cualquier cambio de rumbo se registra acá.

## 1. Visión

**CampoBot** (nombre provisorio): un **asistente por WhatsApp para profesionales del campo**,
con dos módulos sobre una misma plataforma (especificación funcional "Bots AyT Tandil"):

- **Módulo ganadero (veterinario de manga):** tacto y ecografía, raspaje de toros, sanidad
  (planes oficiales, dosis, carencias), liquidación de visita y honorarios.
- **Módulo agrícola (agrónomo / asesor):** siembra y densidad, fertilización, nutrición,
  recorrida, pulverización (caldo, Delta T), cosecha (pérdidas de trilla INTA, silobolsas,
  carta de porte).

Entrada principal por **voz** en el campo, salida por WhatsApp, PDF con la marca CampoBot
y Excel/CSV. **Un solo bot**: el perfil de cada usuario define qué módulos usa.

## 2. Principios

1. **La IA interpreta, el código decide.** La IA convierte el mensaje en acciones con un
   esquema estricto. Todo lo que se guarda, calcula y responde lo hace el código.
2. **Calcula y compara con fuente, no recomienda.** El bot hace cuentas sobre lo que dicta
   el profesional y compara contra umbrales publicados citando la fuente. Nunca indica qué
   hacer (Art. 208 Cód. Penal: es un auxiliar de cálculo y registro, no prescribe).
3. **Los datos de cada cuenta son privados.** El aislamiento se aplica en una sola capa de
   acceso a datos, nunca a mano en cada consulta.
4. **Fórmulas puras y parámetros con fuente.** Cálculos sin efectos secundarios y testeados;
   umbrales y tablas en archivos versionados que citan su origen.
5. **Módulos enchufables.** Agregar una funcionalidad es agregar archivos en su módulo, sin
   tocar el núcleo.
6. **Nada se rompe en silencio.** Tests, lint y chequeo de tipos en cada cambio; migraciones
   para que los datos sobrevivan.
7. **Todo se pide hablando normal.** Cada función del bot se puede pedir con frases completas
   y de cualquier forma razonable, por texto o audio: voseo, muletillas ("che", "bueno",
   "ehh"), errores de transcripción, frases largas y varios pedidos juntos. Los comandos
   escritos son **atajos**: si el mensaje es exactamente el comando, se responde sin IA; si
   no, la IA reconoce el pedido y lo deriva al **mismo manejador**, con la misma respuesta
   armada por el código. Si el pedido es ambiguo, el bot pregunta con una pregunta fija en
   vez de adivinar.

## 3. Estructura del código (objetivo)

Desde la etapa 0 el código sigue esta estructura; las carpetas sin contenido todavía
(`calculos/`, `parametros/`, `modulos/ganaderia/`, `modulos/agricultura/`) se crean en su etapa.

```
app/
  api/            rutas web finas: webhook, /privacidad, salud
  canales/        WhatsApp: parseo de entrada, envío de texto y documentos. Aislado del resto
  nucleo/         pipeline del mensaje, acceso y alta de usuarios, cuentas y perfiles,
                  sesiones (abrir/cerrar manga o lote), registro de acciones, permisos
  ia/             proveedor de IA detrás de una interfaz (OpenRouter y Groq), armado del prompt por
                  perfil, esquemas estrictos de salida, glosario para la transcripción
  modulos/
    comun/          cuaderno, consultar, corregir, borrar, precios, SENASA
    ganaderia/      tacto, raspaje, sanidad y carencias, visita y honorarios
    agricultura/    siembra, fertilización, recorrida, pulverización, cosecha
  calculos/       fórmulas puras (sin base ni IA)
  parametros/     umbrales y tablas con fuente citada (INTA, humedades base, etc.)
  fuentes/        datos externos (pizarras, SENASA, clima) con caché y procedencia
  salidas/        formato WhatsApp, PDF con la marca del producto, Excel/CSV
  infra/          configuración, base de datos, migraciones, logs
```

Cada módulo declara, para cada acción: su **esquema** (qué puede devolver la IA), su
**manejador** (qué hace el código), su **formato** (cómo se muestra) y su aporte al
**glosario** y al **prompt**. El núcleo descubre los módulos y arma el prompt solo con los
del perfil del usuario (menos tokens, menos latencia, más precisión).

## 4. Decisiones

| Tema | Decisión | Motivo |
|---|---|---|
| Salida de la IA | Esquemas Pydantic estrictos; lo que no valida se descarta | Robustez y defensa ante manipulación del prompt |
| Prompt | Compuesto según el perfil del usuario | Latencia (meta < 3 s) y precisión |
| Registros | Columnas comunes + datos específicos por tipo, validados por esquema | Sumar tipos sin migrar la base |
| Entidades | Establecimientos, lotes, animales (RP/caravana) y sesiones como tablas | Trazabilidad (1.° y 2.° raspaje del mismo toro) |
| Multiusuario | Todo pertenece a una **cuenta** (hoy 1 persona = 1 cuenta) | Estudios con varios profesionales en el futuro |
| Base de datos | SQLAlchemy + **Alembic** | Los datos de producción sobreviven a cada cambio |
| Configuración | `pydantic-settings`, validada al arrancar | Falla temprano y con mensaje claro |
| Alertas | Se guardan como **pendientes** consultables ("¿qué tengo pendiente?") | Los avisos automáticos cuestan; se agregan después sobre los mismos datos |
| Nombre | **CampoBot** (provisorio) | Decisión de producto |
| PDF | Con logo y marca CampoBot | Decisión de producto |
| Alta de usuarios | **Código de invitación** + alta guiada. La aprobación del administrador se suma después sobre el mismo flujo | Entran al instante, sin carga manual ni mensajes pagos; control de quién entra |
| Producción | **Railway** desde la etapa 1: el bot, Postgres y el cron `actualizar-precios` (`30 21 * * 1-5`). Cada push a la rama despliega y migra al arrancar, sin esperar al CI | Se adelantó (el plan lo dejaba para la etapa 4): las pruebas desde el celular son contra Railway |
| IA | Interpretar: `openai/gpt-oss-120b` por **OpenRouter** (con `OPENROUTER_API_KEY`), solo con proveedores de retención cero (`zdr`), que no guardan ni entrenan con los datos (`data_collection: deny`) y que aceptan todos los parámetros del pedido (`require_parameters`); **Groq** de respaldo si OpenRouter falla, o como único si no hay clave. Audios: Whisper en Groq | Groq no habilita el plan pago y con el gratuito el bot atiende un mensaje por minuto |

## 5. Seguridad

- Firma del webhook de Meta **obligatoria**: sin secreto configurado el servidor no arranca.
- Logs sin datos personales: teléfonos enmascarados y sin contenido de mensajes.
- Mensajes del mismo usuario procesados **en orden**; reintentos idempotentes.
- Aislamiento por cuenta en la capa de acceso a datos.
- Auditoría de acciones sensibles (borrados, altas y bajas, cambios de rol).
- Límite de mensajes y tope de costo de IA por cuenta.
- PDF y Excel generados sin interpretar texto del usuario como código.
- Dependencias fijadas; CI con lint, tipos y tests.
- Privacidad: política pública, `borrar mis datos`, datos personales fuera del repositorio.

## 6. Plan por etapas

### Etapa 0 · Refactor de base (sin funciones nuevas) ✅

Objetivo: la estructura nueva con **el mismo comportamiento** que hoy y todos los tests en verde.

- [x] Reorganizar el código en `api/`, `canales/`, `nucleo/`, `ia/`, `modulos/comun/`,
      `fuentes/`, `salidas/`, `infra/`; partir `bot.py` en piezas con una sola responsabilidad.
- [x] Registro de acciones: cada acción con esquema, manejador y formato; el núcleo las despacha.
- [x] Esquemas Pydantic para la salida de la IA (reemplazan las validaciones a mano).
- [x] Proveedor de IA detrás de una interfaz (Groq como primera implementación).
- [x] Capa de acceso a datos con aislamiento por usuario/cuenta.
- [x] Configuración con `pydantic-settings`; firma de Meta obligatoria fuera de desarrollo.
- [x] Alembic con una migración inicial equivalente al esquema actual.
- [x] Logs con teléfonos enmascarados.
- [x] Procesamiento en orden por usuario.
- [x] Herramientas: `ruff` (lint y formato), `mypy`, `pytest`; GitHub Actions que los corre.
- [x] Actualizar README y este documento.

**Terminado cuando:** todos los tests actuales pasan sin cambiar lo que verifican, el bot se
comporta igual desde WhatsApp y el CI está en verde.

**Cómo quedó:**

- **Camino del mensaje** (`nucleo/pipeline.py`): acceso → comandos fijos → límites → IA →
  validación con el esquema de cada acción → manejador. El núcleo busca la acción en el
  registro (`nucleo/acciones.py`) por su `intencion`; no conoce las acciones.
- **Acciones** (`modulos/comun/`): un archivo por acción con su esquema Pydantic, su
  manejador y su formato. `modulos.cargar()` registra las de cada módulo de `MODULOS`.
  El formato de los registros sigue compartido en `salidas/whatsapp.py`.
- **Datos por persona** (`nucleo/cuaderno.py`): única puerta a registros, charla, cupo y
  borrados pendientes; un test falla si otro módulo filtra por usuario a mano. Hoy el
  dueño es el usuario; cuando existan las **cuentas** (etapa 1), el cuaderno pasa a
  filtrar por cuenta en este único lugar.
- **IA** (`ia/`): `ProveedorIA` (interfaz), `ProveedorGroq`, el prompt (el mismo texto de
  antes) y los tipos que limpian la salida.
- **Configuración** (`infra/config.py`): `ENTORNO=produccion` por defecto. En producción el
  servidor no arranca sin `META_APP_SECRET`, `WA_VERIFY_TOKEN`, `WA_TOKEN`,
  `WA_PHONE_NUMBER_ID` y `GROQ_API_KEY`. Con secreto, la firma se valida siempre.
- **Migraciones** (`infra/migraciones/`, `infra/migrar.py`): la `0001` es el esquema de
  siempre, congelado en la propia migración. Una base creada antes de Alembic se compara
  con la `0001` (no con los modelos): si coincide se adopta con *stamp* y se aplican las
  migraciones siguientes; si solo le faltan tablas enteras, se crean; si no, no se toca y
  se informa la diferencia. Solo `python -m app db migrar` cambia la base (el `Dockerfile`
  lo corre antes de arrancar); el servidor y los demás comandos no arrancan si falta migrar.
- **Orden** (`infra/orden.py`): una fila por número dentro del proceso, cada una en su hilo.
  Alcanza con una instancia y un worker (`--workers 1`); con varias habrá que llevarla a
  la base o a una cola externa.
- **Terminal**: un solo punto de entrada, `python -m app <comando>` (`chat`, `usuarios`,
  `precios`, `senasa`, `db`).

**Quedó para las etapas siguientes:**

- Armar el prompt según el perfil del usuario: hoy es uno solo, en `ia/prompt.py`, y cada
  acción nueva se describe ahí. Pasa a armarse por módulo con los perfiles (etapa 1).
- Las carpetas `calculos/` y `parametros/`, y los módulos `ganaderia/` y `agricultura/`, se
  crean cuando tengan su primer contenido (etapas 2 y 3).

### Etapa 0.1 · Correcciones de la etapa 0

Revisión de la etapa 0, con las mismas reglas: comportamiento igual, tests sin aflojar y,
en cada punto, primero un test que reproduce el problema.

- [x] Orden por usuario: el webhook encola todo al recibirlo (por timestamp) y cada persona
      tiene su propio hilo; un lote ya no se intercala con el webhook siguiente ni una
      persona espera a otra. Al apagarse, el servidor espera los mensajes recibidos.
- [x] Postgres: driver `psycopg` (v3), el que usa SQLAlchemy 2.1 para `postgresql://`; job
      de CI con un servicio Postgres que corre las migraciones y todos los tests.
- [x] Adopción de bases viejas contra el esquema de la `0001` (congelado en la migración),
      no contra los modelos; si solo faltan tablas enteras, se crean; error legible.
- [x] Logs sin datos personales: `hide_parameters`, errores de Groq con tipo y código, uvicorn
      enmascarado y sin query string, 10 a 15 dígitos, sin wamid, ids de mensajes por 7 días.
- [x] Respuesta vacía de la IA: error ("no pude procesar"), como antes.
- [x] Registro de acciones cargado una vez al arrancar (servidor y terminal), con candado.
- [x] Menores: `limpiar_texto`, variables vacías en el `.env`, `ZONA_HORARIA` inválida, firma
      no ASCII (401), timestamp mal formado, tests aislados del entorno, `--workers 1`,
      hooks de ruff para migraciones generadas, solo `db migrar` migra, README para cmd,
      chat sin logs de httpx, `test-prompt.py` borrado, pantallas nuevas de Meta.
- [x] Convención de nombres para los constraints, la misma que usa Postgres por defecto:
      las bases de Postgres ya la cumplían (no se migró nada) y la `0002` nombra los de
      SQLite, que estaban sin nombre (recrea las tablas, sin tocar los datos).

**Cambios de comportamiento aceptados** (vienen de la etapa 0; se dejan así):

- Con salidas raras de la IA, "gracias, chau" ahora responde "¡De nada!".
- Las correcciones con valores que no se entienden piden aclaración, en vez de guardar el
  campo vacío.
- Las referencias de borrado que no se entienden piden aclaración, en vez de tomar todos
  los registros.

### Etapa 1 · Núcleo profesional

- **Alta por código de invitación** (ver "Alta de usuarios" abajo).
- Perfiles por rubro que habilitan módulos, además del común que tienen todos: veterinario →
  ganadería; agrónomo / asesor → agricultura; productor → ambos.
- Establecimientos y lotes como entidades; sesiones con apertura, cierre y resumen.
- Salidas: PDF con marca del producto y Excel/CSV enviados por WhatsApp.
- Glosario para Whisper por perfil.
- Set de evaluación (frase → acciones esperadas) armado con: las frases de la especificación,
  las pruebas del administrador simulando clientes (un **modo prueba** guarda transcripción e
  interpretación, sin guardar audios) y frases escritas por profesionales de contacto.
- "¿Qué tengo pendiente?".

**Alta de usuarios:**

- **Invitar:** el administrador manda `invitar` y recibe un código (por ejemplo
  `CAMPO-7K3P`) y un link `wa.me/<número del bot>?text=<código>` para reenviar. El link abre
  el chat con el código ya escrito.
- **Reglas del código:**
  - Sirve para una sola persona y vence a los 7 días.
  - Se puede anular. `invitaciones` lista los códigos vigentes.
  - Tiene que ser difícil de adivinar, y hay un límite de intentos fallidos por número.
- **Alta guiada:** quien manda un código válido completa nombre y apellido, rubro y localidad
  con preguntas fijas, sin IA. Al terminar queda habilitado y el rubro define su perfil.
- **Sin código:** un mensaje fijo ("CampoBot está en prueba privada…"). No llega a la IA.
- Los usuarios ya autorizados y el comando `autorizar <número>` siguen funcionando.
- **Preparado para sumar la aprobación del administrador** sin rehacer nada:
  - El alta es una **solicitud** con estado (pendiente, aprobada, rechazada) y origen
    (código o pedido). Con código se aprueba sola.
  - Sumar la aprobación es agregar el origen "pedido" (alta guiada sin código, queda
    pendiente) y los comandos `pendientes`, `aprobar <n>` y `rechazar <n>`.
  - Los avisos al administrador y al usuario tienen que respetar la ventana de 24 h de
    WhatsApp: fuera de ella son mensajes pagos.

**Pasos** (un commit por paso, CI en verde; se frena para probar desde el celular después
de 2b, 7 y 8b):

- [x] 0 · Preparación: nombre CampoBot en los textos, `docs/privado/` fuera del repo, tests de
      migraciones con bases viejas armadas con el esquema congelado de la `0001`.
- [x] 1a · Cuentas: todo pertenece a una cuenta; el cuaderno filtra por cuenta. En SQLite
      las migraciones son transaccionales (BEGIN explícito): si una falla, no queda a medias.
- [x] 1b · Perfil: nombre y apellido, rubro y localidad con preguntas fijas; `mis datos`,
      `cambiar rubro`, `cambiar matrícula`.
- [x] 2a · Auditoría de acciones sensibles (`python -m app auditoria`).
- [x] 2b · Alta por código de invitación, solicitudes e intentos fallidos.
- [x] 3 · Prompt armado con los módulos del perfil: el núcleo pone lo común a todos y cada
      módulo suma sus intenciones, campos, formatos y reglas; una acción de un módulo que la
      persona no tiene no se ejecuta. Con solo el módulo común, el texto es el mismo de antes.
- [x] 4 · Glosario para Whisper según el perfil: cada módulo declara las palabras que Whisper
      suele escribir mal y el audio se transcribe con las de los módulos del rubro, sin
      repetir (hasta 500 caracteres, por el límite de 224 tokens de Whisper). Si la
      transcripción no trae palabras o solo trae palabras del glosario (Whisper lo devuelve
      a veces con un audio en silencio o muy corto), es un audio vacío: no llega a la IA y
      se le pide a la persona que lo repita.
- [x] 5 · Establecimientos y lotes como tablas; `mis campos`. La `0007` pasa a tablas los
      nombres que estaban como texto en los registros (un establecimiento por cuenta y
      clave, con el nombre del primer registro; un lote por cuenta, establecimiento y
      nombre) y borra las columnas de texto (no estaba aprobado; se aceptó después, porque
      la migración tiene vuelta atrás y está probada). Hacer una copia de la base antes de
      migrar.
- [x] 6 · Sesiones con apertura, cierre y resumen (`nucleo/sesiones.py`; las acciones
      `abrir_sesion` y `cerrar_sesion` del módulo común; comando fijo `cerrar sesión`). La
      `0009` solo agrega la tabla `sesiones` y `eventos.sesion_id`. Se aceptaron después
      cuatro cosas que el plan no decía:
      1. "estoy en El Ombú" con una sesión abierta en otro campo avisa que lo que se anote
         sin campo sigue yendo a la sesión, y cómo cerrarla: "Si ya terminaste en El
         Retiro, decí _terminamos_ y te paso el resumen."
      2. Un registro que nombra otro campo durante una sesión queda fuera de ella y además
         deja ese campo como actual: mientras la sesión sigue abierta no cambia nada; al
         cerrarse, lo que no nombra campo va a ese campo.
      3. La confirmación de un registro que entró en la sesión agrega "▶️ en la sesión".
      4. El bloque de totales pasó de la consulta a `salidas/whatsapp.py`, para usarlo
         también en el resumen; la consulta muestra lo mismo que antes.
- [x] 7 · Pendientes (`modulos/comun/pendientes.py`: las acciones `anotar_pendiente`,
      `ver_pendientes`, `pendiente_hecho` y `borrar_pendiente`). Para marcar hecho o borrar,
      todas las palabras con las que la persona nombra el pendiente tienen que estar en él
      (en su texto, su lote o su campo; "llamé" y "llamar" coinciden); si coincide con varios
      no se toca ninguno y se muestran las opciones, salvo que pida todos. Los hechos se
      guardan con su fecha y salen de la lista. La `0010` solo agrega la tabla `pendientes`.
- [x] 7.1 · Ajustes de pendientes: el texto, hasta 120 caracteres y sin `*`, `_` ni `~`;
      borrar 4 o más pide confirmación, como con los registros. La `0011` solo agrega a
      `borrados_pendientes` qué se va a borrar (registros o pendientes).
- [x] 7.2 · Todo se pide hablando normal (principio 7): mis campos, mis datos, cambiar
      rubro, cambiar matrícula, privacidad, ayuda y borrar mis datos pasan a ser también
      intenciones de la IA (`modulos/comun/cuenta.py`), con el mismo manejador que su atajo.
      El prompt avisa que los audios traen muletillas y errores, y "aclarar" suma
      `que_pedido` para lo que no se entiende. El set de evaluación arranca en
      `evaluacion/set.json` con al menos 5 formas de pedir cada función (un test lo
      controla). Contra Groq se probó una muestra (7 de 7 bien): el set entero no entra en
      el plan gratuito (8000 tokens por minuto y cada mensaje usa unos 4700).
- [x] 8a · Envío de documentos por WhatsApp y PDF. La acción `exportar` (pedida hablando:
      "mandame un PDF de lo que hice este mes") usa los mismos filtros que `consultar`; el
      manejador suma el archivo a la respuesta (`Contexto.adjuntos`) y el webhook lo sube a
      Meta y lo manda como documento después del texto. El PDF (`salidas/pdf.py`, fpdf2 con
      Helvetica) lleva el membrete, de qué es, los totales, una fila por registro del más
      viejo al más nuevo y el pie legal con el número de página. El texto de la persona va
      tal cual (sin markdown ni HTML) y lo que la fuente no tiene, como los emojis, se saca.
      Sin logo todavía (pendiente de definición): la marca es el nombre.
- [x] 8b · Excel y CSV, con la misma acción `exportar` (`salidas/planilla.py`, openpyxl).
      El Excel tiene la hoja "Registros" (una columna por dato, con números y fechas como
      tales, filtro y encabezado fijo) y la hoja "Resumen" (membrete, de qué es, totales y
      pie legal). El CSV, solo esa tabla, con `;`, coma decimal y BOM. El texto de la persona
      nunca se toma como fórmula (en Excel va como texto; en el CSV, con un apóstrofo
      adelante si empieza con =, +, - o @). WhatsApp no acepta `text/csv` como documento: el
      CSV se sube como texto plano, con su nombre `.csv`.
- [x] 8.1 · Respuestas fijas más flexibles, sin IA: la pregunta del rubro acepta el número o
      la palabra ("agrónomo", "vete", "productor"), y los *sí* / *no* de una confirmación
      aceptan variantes comunes ("dale", "ok", "sí, borrá", "no, dejá"). Si la respuesta
      mezcla un sí y un no, o trae otra cosa, no es una respuesta y sigue su camino normal.
      Las variantes están en `nucleo/respuestas.py` (también para cancelar un cambio de
      rubro o matrícula). El número del rubro vale solo o con el rubro y relleno ("opción
      2", "2, agrónomo"): "vacuné 3 vacas" ya no se toma como la opción 3, y "1 agrónomo"
      vuelve a preguntar.
- [x] 8.2 · IA por OpenRouter (decisión "IA", arriba):
      - Un `ProveedorIA` nuevo para OpenRouter (API compatible con OpenAI). Con
        `OPENROUTER_API_KEY`, OpenRouter interpreta y Groq queda de respaldo; sin la clave, todo
        sigue con Groq, sin fallar al arrancar.
      - Si la IA rechaza por límite, no responde o no hay saldo, el bot contesta "⏳ Estoy con
        mucha demanda, probá de nuevo en un minuto" en vez del error genérico, y queda en los
        logs sin datos personales.
      - Política de privacidad: el texto lo procesa OpenRouter con el proveedor del modelo (Groq
        si OpenRouter no responde) y los audios Groq, sin uso para entrenar.
      - `python -m app eval` se adelanta del paso 9b: corre el set entero o una parte, muestra
        llamadas, tokens, costo estimado y latencia (mediana y p95), y frena si pasa un tope
        configurable. Antes de correr algo que cueste más de USD 0,50, se pregunta.
      - Esfuerzo de razonamiento: se compara `low` contra `medium` con el set y se muestra la
        comparación antes de cambiarlo (hasta entonces, `medium`, el que usaba Groq).
      - Un test controla el tamaño del prompt de cada rubro, con un tope.

      Cómo quedó: `ia/proveedor_openrouter.py` (con httpx, sin dependencias nuevas; espera
      20 s, 12 desde el 8.3, y pasa al respaldo), `ConRespaldo` en `ia/proveedor.py` y `IASaturada` para 402,
      408, 429, 5xx y sin respuesta (en Groq: límite, sin conexión o caído), también al
      transcribir un audio. Cada pedido deja en el log quién respondió, tokens, costo y
      demora, y al arrancar se loguea qué IA se usa. `python -m app eval` tiene `--funcion`,
      `--desde`, `--limite`, `--proveedor`, `--esfuerzo`, `--rubro`, `--tope-usd` (0,50 por
      defecto) y `--pausa`; Groq no informa el costo. Tope del prompt: 24.000 caracteres
      por rubro (`LARGO_MAXIMO_PROMPT`; hoy 16.600). La comparación de esfuerzo pasó al 8.3.
- [ ] 8.3 · Ajustes de la IA (los cambios extra del 8.1 y el 8.2 quedan aceptados):
      - OpenRouter espera 12 s antes de pasar al respaldo (20 s más el respaldo es demasiado;
        la meta es responder en menos de 3 s). Después se ajusta con la p95 del eval.
      - Si la IA está saturada o falla, ese mensaje no cuenta para el límite diario.
      - Retención cero (`zdr`) además de `data_collection: deny`: para
        `openai/gpt-oss-120b` hay varios proveedores con retención cero que aceptan todos los
        parámetros del pedido. La política de privacidad lo dice.
      - Comparación de esfuerzo `low` contra `medium` con el set completo; se muestra la
        tabla antes de cambiarlo.
- [ ] 9a · Modo prueba.
- [ ] 9b · Set de evaluación armado con el modo prueba (`eval revisar`); el comando
      `python -m app eval` ya existe desde el 8.2.

**Decisiones de producto de la etapa 1:**

- **Usuarios existentes:** al escribir, si les falta nombre, rubro o localidad, el mensaje se
  descarta, se hacen las preguntas fijas y al final se les pide repetirlo. Los administradores
  también las responden.
- **Rubro:** Veterinario, Agrónomo o asesor, o Productor. La opción "Otro" se sacó: a quien
  la tenía se le vuelve a preguntar el rubro la próxima vez que escribe (el mensaje se
  descarta, como con cualquier dato que falta). Se ve con `mis datos` (nombre,
  rubro, localidad y matrícula) y se cambia con `cambiar rubro`, o pidiéndolo con
  cualquier frase ("Todo se pide hablando normal", abajo).
- **Localidad:** texto libre, prolijo (mayúscula inicial, sin espacios de más).
- **Matrícula:** opcional y fuera del alta (que sigue siendo de 3 preguntas); se carga con
  `cambiar matrícula`. Si está, va en el membrete del PDF.
- **Código de invitación:** 8 caracteres (`CAMPO-XXXX-XXXX`), precargado en el link. Al usarse
  queda atado a ese número, que puede retomar el alta durante 7 días; después se borra lo
  cargado y el código queda gastado.
- **Intentos fallidos:** 5 cada 24 h por número (teléfono guardado con HMAC y `CLAVE_HASH`),
  sin avisar del bloqueo.
- **Auditoría:** solo ids numéricos; las filas se conservan después de `borrar mis datos`. Se
  consulta con `python -m app auditoria`.
- **Establecimientos y lotes:** `mis campos` los lista (atajo sin IA, o pidiéndolo con
  cualquier frase: "che, ¿qué campos tengo cargados?"). El nombre
  de un establecimiento es el de la primera vez que se nombró, guardado prolijo como la
  localidad ("Estancia de la Sierra", "El Ombú"); la `0008` ordena los que ya existían. Unir
  duplicados y un comando `renombrar campo` quedan para más adelante.
- **Campo actual:** un registro que no nombra campo va al último establecimiento que la
  persona nombró, con "estoy en La Pastora" (aunque no anote nada) o con un registro que
  nombra un campo. Las consultas, las correcciones y los borrados que nombran un campo no
  lo cambian. Con una sesión abierta, el campo de los registros sin campo es el de la sesión.
- **Sesiones:** una abierta por persona; al abrir otra, la anterior se cierra con su resumen.
  Se abren con una frase que reconoce la IA, con el campo, el lote y la actividad ("arranco
  manga en El Retiro", "empiezo siembra lote Los Pinos"), y se cierran con "terminamos",
  "cerramos" o el comando fijo `cerrar sesión`, que muestra el resumen. "estoy en X" no abre
  sesión: si hay una abierta en otro campo, avisa que sigue abierta y cómo cerrarla. Un
  registro que no nombra campo va a la sesión y hereda su campo y lote (la lluvia
  no hereda el lote: es del campo); uno de otro establecimiento queda fuera, con aviso, y los
  siguientes sin campo siguen yendo a la sesión. Se cierra sola a las 12 h sin actividad
  (cualquier mensaje de la persona cuenta): cuando la persona vuelve a escribir se le avisa y
  se le muestra el resumen (sin mensajes automáticos).
- **Pendientes:** se anotan, se consultan, se marcan hechos ("ya está lo del lote 3") y se
  borran. Los vencidos van primero y destacados (⚠️). Respuestas del paso 7:
  - Un pendiente que no nombra campo toma el de la sesión abierta o el campo actual, como
    los registros, sin heredar el lote. Uno que nombra un campo va a ese y no cambia el
    campo actual (como las consultas).
  - `borrar` deshace lo último que se anotó, sea un registro o un pendiente.
  - Sin comando fijo: se consultan por la IA ("¿qué tengo pendiente?", "pendientes").
    `pendientes` como comando queda para el administrador (aprobar altas).

  Aceptado después del paso 7 (con los límites del 7.1):
  - El texto del pendiente lo recorta la IA de las palabras de la persona y el bot lo
    muestra: hasta 120 caracteres y sin los símbolos de formato de WhatsApp (`*`, `_`, `~`),
    para que no desarme la respuesta.
  - Para encontrar un pendiente, todas las palabras con las que se lo nombra tienen que
    estar en su texto, su lote o su campo, comparadas por el principio.
  - Borrar 4 o más pendientes de una vez pide confirmación (*sí* / *no*), igual que con los
    registros. Marcar hechos con "todos" no la pide.
  - Los hechos se guardan con su fecha y salen de la lista; todavía no se consultan.
  - Borrar pendientes queda en la auditoría, como borrar registros.
- **Todo se pide hablando normal** (principio 7). Vale para mis campos, mis datos, cambiar
  rubro, cambiar matrícula, privacidad, ayuda / qué podés hacer, borrar (deshacer lo
  último), cerrar sesión y pendientes, solos o junto con otros pedidos ("mostrame mis
  campos y qué tengo pendiente"). Los comandos escritos siguen como atajos exactos, sin IA,
  y la ayuda muestra frases naturales como ejemplos y los comandos como atajos.
  - Si no se entiende qué función pide, una pregunta fija ("¿Qué necesitás?…").
  - Excepciones por seguridad:
    - `borrar mis datos`: la IA reconoce el pedido y muestra el aviso de siempre, pero
      borrar exige escribir exacto `confirmo borrar mis datos`.
    - Comandos del administrador (`invitar`, `invitaciones`, `anular`, `autorizar`,
      `quitar`, `autorizados`): solo exactos y escritos; no pasan por la IA.
  - Siguen fijas, sin IA, las respuestas a una pregunta del bot (el rubro, por número o
    palabra; *sí* / *no* de un borrado grande, con variantes como "dale" o "no, dejá";
    *cancelar*) y, durante el alta, que es sin IA, solo valen los atajos `ayuda` y
    `privacidad`.
  - El set de evaluación tiene al menos 5 formas distintas de pedir cada función, con
    frases largas, muletillas y como salen de un audio.
- **Salidas:** "Excel" o "planilla" → .xlsx; CSV solo si lo pide, con `;` y BOM. El PDF lleva
  nombre, rubro y localidad (y matrícula, si está) y al pie: "Registro de lo informado por el
  profesional. CampoBot es un auxiliar de cálculo y registro: no realiza recomendaciones ni
  reemplaza la prescripción profesional." En esta etapa el PDF le llega solo al profesional,
  que lo reenvía; el envío directo al productor va después de las alertas pagas.
- **Modo prueba:** `modo prueba` / `fin modo prueba`, solo el administrador en su número.
  `eval revisar` lee la base local; para otra base, `--base` explícito y en solo lectura. Lo
  aprobado se guarda solo en `evaluacion/set.json`.
- **Set de evaluación:** las frases de la especificación entran con lo esperado hoy; cada
  etapa sube la versión y cambia lo esperado. `python -m app eval` contra la IA real solo
  cuando cambia el prompt o un esquema, informando llamadas, tokens, costo y latencia, con
  un tope de costo.
- **Trilla (etapa 3):** el bot informa qué componente de la pérdida supera la tolerancia del
  INTA, citando la fuente, sin decir qué hacer.

### Etapa 2 · Módulo ganadero

Tacto y cierre (preñez por cabeza/cuerpo/cola, % y CC promedio, PDF), raspaje (RP, muestreos,
resultado de laboratorio, pendiente de repetición), sanidad (planes oficiales, dosis, consumo,
carencia), visita y honorarios (tarifas del profesional).

**Glosario:** pasan del glosario del módulo común al de ganadería ivermectina, aftosa,
brucelosis, tacto, manga y destete, así el común queda corto y el rubro tiene lugar para
las suyas.

**Aceptación:** los ejemplos de la especificación funcionan de punta a punta
("Terminamos lote vaquillonas San Pedro…", "Toro caravana 405 raspaje negativo…",
"Pasamos 140 terneros con 4 ml de Ivermectina 1%…").

### Etapa 3 · Módulo agrícola

Siembra y densidad, fertilización e índice salino, nutrición, recorrida (con ubicación),
caldo y Delta T, pérdidas de trilla (INTA), silobolsas, carta de porte.

**Glosario:** pasan del glosario del módulo común al de agricultura fumigación,
fertilización, girasol y sorgo.

**Aceptación:** los ejemplos de la especificación funcionan de punta a punta
("Para 160 ha: 2.2 l Atrazina…", "Aros en soja lote 5…", "Cerramos bolsa 3 de trigo…",
"Cotización disponible trigo y cebada cervecera Quequén").

### Etapa 4 · Prueba con testers

Servidor en la nube (ya está: Railway, desde la etapa 1), número propio en Meta, monitoreo, medición de precisión con el set de
evaluación, ajustes según el uso real. Opcional: que los usuarios acepten que sus
transcripciones, anonimizadas, se sumen al set de evaluación.

### Después del MVP

Alertas automáticas (mensajes pagos de Meta), cuentas con varios profesionales, panel web,
cobros, fotos en recorridas (modelo de visión), Matba-Rofex y dólar exportador.

## 7. Pendientes de definición

- Logo de CampoBot (para el PDF). El nombre es provisorio.
- Cómo cobran los veterinarios (por hora, animal, km) para el cálculo de honorarios.
- Fuente oficial de carencias por producto (el registro de SENASA descargado no las incluye).
- Publicaciones oficiales de cada umbral: tolerancias de trilla INTA, humedades base,
  densidades para silobolsas, índice salino.
