# Arquitectura y plan de desarrollo

Documento de referencia del proyecto: qué construimos, cómo está organizado el código, qué
decisiones tomamos y en qué orden avanzamos. Cualquier cambio de rumbo se registra acá.

## 1. Visión

Un **asistente por WhatsApp para profesionales del campo**, con dos módulos sobre una misma
plataforma (especificación funcional "Bots AyT Tandil"):

- **Módulo ganadero (veterinario de manga):** tacto y ecografía, raspaje de toros, sanidad
  (planes oficiales, dosis, carencias), liquidación de visita y honorarios.
- **Módulo agrícola (agrónomo / asesor):** siembra y densidad, fertilización, nutrición,
  recorrida, pulverización (caldo, Delta T), cosecha (pérdidas de trilla INTA, silobolsas,
  carta de porte).

Entrada principal por **voz** en el campo, salida por WhatsApp, PDF con la marca del producto
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

## 3. Estructura del código (objetivo)

Desde la etapa 0 el código sigue esta estructura; las carpetas sin contenido todavía
(`calculos/`, `parametros/`, `modulos/ganaderia/`, `modulos/agricultura/`) se crean en su etapa.

```
app/
  api/            rutas web finas: webhook, /privacidad, salud
  canales/        WhatsApp: parseo de entrada, envío de texto y documentos. Aislado del resto
  nucleo/         pipeline del mensaje, acceso y alta de usuarios, cuentas y perfiles,
                  sesiones (abrir/cerrar manga o lote), registro de acciones, permisos
  ia/             proveedor de IA detrás de una interfaz (hoy Groq), armado del prompt por
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
| PDF | Con logo y marca del producto | Decisión de producto |
| Alta de usuarios | Alta guiada + aprobación del administrador, o código de invitación | Sin carga manual; control de quién entra |

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

- Alta guiada (nombre, apellido, rubro, localidad), aprobación y códigos de invitación.
- Perfiles por rubro que habilitan módulos.
- Establecimientos y lotes como entidades; sesiones con apertura, cierre y resumen.
- Salidas: PDF con marca del producto y Excel/CSV enviados por WhatsApp.
- Glosario para Whisper por perfil.
- Set de evaluación (frase → acciones esperadas) armado con: las frases de la especificación,
  las pruebas del administrador simulando clientes (un **modo prueba** guarda transcripción e
  interpretación, sin guardar audios) y frases escritas por profesionales de contacto.
- "¿Qué tengo pendiente?".

### Etapa 2 · Módulo ganadero

Tacto y cierre (preñez por cabeza/cuerpo/cola, % y CC promedio, PDF), raspaje (RP, muestreos,
resultado de laboratorio, pendiente de repetición), sanidad (planes oficiales, dosis, consumo,
carencia), visita y honorarios (tarifas del profesional).

**Aceptación:** los ejemplos de la especificación funcionan de punta a punta
("Terminamos lote vaquillonas San Pedro…", "Toro caravana 405 raspaje negativo…",
"Pasamos 140 terneros con 4 ml de Ivermectina 1%…").

### Etapa 3 · Módulo agrícola

Siembra y densidad, fertilización e índice salino, nutrición, recorrida (con ubicación),
caldo y Delta T, pérdidas de trilla (INTA), silobolsas, carta de porte.

**Aceptación:** los ejemplos de la especificación funcionan de punta a punta
("Para 160 ha: 2.2 l Atrazina…", "Aros en soja lote 5…", "Cerramos bolsa 3 de trigo…",
"Cotización disponible trigo y cebada cervecera Quequén").

### Etapa 4 · Prueba con testers

Servidor en la nube, número propio en Meta, monitoreo, medición de precisión con el set de
evaluación, ajustes según el uso real. Opcional: que los usuarios acepten que sus
transcripciones, anonimizadas, se sumen al set de evaluación.

### Después del MVP

Alertas automáticas (mensajes pagos de Meta), cuentas con varios profesionales, panel web,
cobros, fotos en recorridas (modelo de visión), Matba-Rofex y dólar exportador.

## 7. Pendientes de definición

- Nombre del producto y logo (para PDF y mensajes).
- Cómo cobran los veterinarios (por hora, animal, km) para el cálculo de honorarios.
- Fuente oficial de carencias por producto (el registro de SENASA descargado no las incluye).
- Publicaciones oficiales de cada umbral: tolerancias de trilla INTA, humedades base,
  densidades para silobolsas, índice salino.
- Alta de usuarios: aprobación manual, código de invitación o ambos.
