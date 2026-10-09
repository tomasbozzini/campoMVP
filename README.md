# Asistente de campo por WhatsApp 🐄

Bot de WhatsApp para registrar lo que pasa en el campo y consultarlo después, en lenguaje natural y con audios.

```
vos> Hoy vacunamos 20 vacas contra aftosa en el lote 3
bot> Anotado:
     • Vacunación (aftosa) · 20 vacas · lote 3 · 09/10/2026

vos> ¿Cuántas vacas se vacunaron este mes?
bot> Este mes se vacunaron *35 vacas*: 20 en el lote 3 (09/10) y 15 en el lote 5 (02/10).
```

## Qué hace

- **Registra eventos** de sanidad (vacunación, desparasitación, tratamientos), movimientos de hacienda (nacimientos, muertes, compras, ventas, traslados), pesadas, reproducción (tacto, servicio, destete) y del campo (lluvias, siembra, fumigación). Un mensaje puede traer varios eventos.
- **Responde preguntas** sobre lo registrado. Los totales los calcula el código, no la IA, para que las sumas den bien.
- **Entiende audios**: los transcribe con Whisper en Groq.
- **Maneja varios campos y varios usuarios**: cada campo tiene sus datos y un código de invitación.
  - `crear campo La Esperanza`: crea el campo y te deja como admin.
  - `unirme K7P2QX`: suma a otra persona a ese campo.
  - `codigo`: muestra el código de invitación.
  - `borrar`: deshace lo último que anotaste.
  - `ayuda`: muestra los ejemplos.

## Cómo funciona

```
WhatsApp ──► Meta Cloud API ──► POST /webhook (FastAPI)
                                   │  verifica la firma y responde 200 enseguida
                                   ▼
                             audio? ──► Whisper (Groq) ──► texto
                                   ▼
                     comandos (crear campo / unirme / borrar...)
                                   ▼
                    el modelo (Groq) clasifica: registrar | consultar | charla
                     │                         │
          guarda Evento(s) en Postgres    arma filtros ──► busca SOLO en el campo del usuario
                                                         ──► la IA redacta la respuesta
```

| Archivo | Qué tiene |
|---|---|
| `app/main.py` | Webhook de WhatsApp: verificación, firma, deduplicación de reintentos y audios |
| `app/bot.py` | Lógica del asistente: comandos, registrar, consultar, borrar |
| `app/llm.py` | Prompts y llamadas a Groq (interpretar, responder, transcribir) |
| `app/consultas.py` | Búsqueda con filtros y totales precalculados |
| `app/models.py` | Tablas: `campos`, `usuarios`, `eventos`, `mensajes_procesados` |
| `app/whatsapp.py` | Envío de mensajes y descarga de audios desde Meta |
| `app/cli.py` | Chat por terminal para probar sin WhatsApp |

**Seguridad:** la IA nunca escribe SQL, solo devuelve filtros, y toda búsqueda se limita al campo del usuario. El webhook valida la firma `X-Hub-Signature-256` de Meta. Los números que no están en ningún campo no pueden registrar ni consultar.

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
