# CampoBot (campoMVP)

Asistente por WhatsApp para profesionales del campo (veterinarios, agrónomos, productores):
anotan el trabajo por voz o texto y lo consultan después. La IA (Groq) solo interpreta el
mensaje con esquemas estrictos; todo lo que se guarda, calcula y responde lo hace el código.
FastAPI + SQLAlchemy + Alembic; SQLite en desarrollo, Postgres en producción (Railway).

## El plan

`docs/arquitectura.md` es **el plan**. Antes de cada paso, releé "2. Principios",
"4. Decisiones" y, en "6. Plan por etapas", la etapa en curso (lista de pasos y "Decisiones
de producto"). `README.md` explica el uso y el funcionamiento.

## Reglas de trabajo

- **Respetar el plan.** Si conviene apartarse (otro enfoque, algo que el plan dice que no se
  hace, un cambio de comportamiento no pedido), **preguntar antes**. Si se aprueba, primero
  se anota en el plan y después se programa.
- Cada resumen de paso termina con **"Cambios respecto del plan"** (o "Ninguno").
- **Un commit por paso**, push al terminar y CI en verde (incluido el job de Postgres).
- Comandos para **cmd de Windows** cuando se le pasan al usuario.
- Nunca subir `.env`, `campo.db`, `*.bak`, `docs/privado/` ni datos personales.
- Leer y buscar archivos con las herramientas (Read, Glob, Grep), no con find, xargs, sed o cat.
- Pausas para probar desde el celular donde el plan lo indica.
- Los textos del bot, los comentarios y los commits van en castellano rioplatense.
- **Todo se pide hablando normal** (principio 7 del plan): cada función nueva es una
  intención de la IA; si además tiene comando escrito, es un atajo exacto que llama al
  mismo manejador. Sumar sus frases al set de evaluación (`evaluacion/set.json`).

## Producción (Railway)

- El bot corre en Railway: el servicio del bot, Postgres y el cron `actualizar-precios`.
  El webhook de Meta apunta ahí.
- **Cada push a la rama despliega solo y migra al arrancar, sin esperar al CI.** Antes de
  cada push: ruff, mypy y pytest en verde (y los tests sobre Postgres si hay migración).
- Si un paso trae una migración que **borra o cambia datos**, avisar **antes de subirla**
  para hacer una copia de la base de Railway.
- Las pruebas desde el celular son contra Railway: las instrucciones no piden ngrok,
  uvicorn ni copiar `campo.db`.

## Chequeos

Los mismos que corre el CI (`.github/workflows/ci.yml`), desde la carpeta del proyecto:

```bat
venv\Scripts\activate
ruff check .
ruff format --check .
mypy
pytest
```

Los tests usan SQLite y no tocan la IA real ni internet. Para correrlos sobre Postgres,
`TEST_DATABASE_URL` con una base **solo para tests** (los tests borran sus tablas). Conviene
hacerlo antes de subir una migración: el job de Postgres detecta cosas que SQLite tapa.
