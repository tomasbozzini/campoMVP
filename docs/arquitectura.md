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

### Etapa 0 · Refactor de base (sin funciones nuevas)

Objetivo: la estructura nueva con **el mismo comportamiento** que hoy y todos los tests en verde.

- [ ] Reorganizar el código en `api/`, `canales/`, `nucleo/`, `ia/`, `modulos/comun/`,
      `fuentes/`, `salidas/`, `infra/`; partir `bot.py` en piezas con una sola responsabilidad.
- [ ] Registro de acciones: cada acción con esquema, manejador y formato; el núcleo las despacha.
- [ ] Esquemas Pydantic para la salida de la IA (reemplazan las validaciones a mano).
- [ ] Proveedor de IA detrás de una interfaz (Groq como primera implementación).
- [ ] Capa de acceso a datos con aislamiento por usuario/cuenta.
- [ ] Configuración con `pydantic-settings`; firma de Meta obligatoria fuera de desarrollo.
- [ ] Alembic con una migración inicial equivalente al esquema actual.
- [ ] Logs con teléfonos enmascarados.
- [ ] Procesamiento en orden por usuario.
- [ ] Herramientas: `ruff` (lint y formato), `mypy`, `pytest`; GitHub Actions que los corre.
- [ ] Actualizar README y este documento.

**Terminado cuando:** todos los tests actuales pasan sin cambiar lo que verifican, el bot se
comporta igual desde WhatsApp y el CI está en verde.

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
