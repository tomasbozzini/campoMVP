"""Política de privacidad, publicada por el mismo bot en /privacidad.

Meta pide una URL pública con la política para publicar la app. El responsable y el
contacto salen de PRIVACIDAD_RESPONSABLE y PRIVACIDAD_CONTACTO.

BORRADOR: revisalo con alguien que sepa de protección de datos antes de tener clientes.
"""

from html import escape

from app.infra.config import config

ULTIMA_ACTUALIZACION = "13 de octubre de 2026"

_PLANTILLA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Política de privacidad · Asistente de campo</title>
<style>
  :root {{ --bg: #f6f7f4; --fg: #1d2620; --muted: #5d6b61; --line: #d4dbd5; --accent: #2f7a4a; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #121713; --fg: #e4ebe5; --muted: #9aa89e; --line: #344038; --accent: #6fc28c; }}
  }}
  body {{ background: var(--bg); color: var(--fg); font: 16px/1.6 "Segoe UI", Roboto, Arial, sans-serif; margin: 0; }}
  main {{ max-width: 720px; margin: 0 auto; padding: 40px 20px 64px; }}
  h1 {{ font-size: 1.9rem; line-height: 1.2; margin: 0 0 6px; }}
  h2 {{ font-size: 1.15rem; margin: 2rem 0 .5rem; color: var(--accent); }}
  p, li {{ max-width: 68ch; }}
  ul {{ padding-left: 1.2rem; }}
  li {{ margin: .3rem 0; }}
  .fecha {{ color: var(--muted); font-size: .9rem; margin: 0 0 1.5rem; }}
  .legal {{ border-top: 1px solid var(--line); margin-top: 2.5rem; padding-top: 1rem; color: var(--muted); font-size: .9rem; }}
  code {{ background: rgba(127,127,127,.15); padding: 1px 6px; border-radius: 4px; }}
</style>
</head>
<body>
<main>
<h1>Política de privacidad</h1>
<p class="fecha">Asistente de campo por WhatsApp · Última actualización: {fecha}</p>

<p>Esta política explica qué datos guarda el Asistente de campo, para qué los usa, con quién los
comparte y cómo podés ejercer tus derechos. Al usar el asistente aceptás este tratamiento de tus datos.</p>

<h2>1. Quién es el responsable</h2>
<p>El responsable de los datos es <strong>{responsable}</strong>. Para cualquier consulta o pedido sobre
tus datos podés escribir a <strong>{contacto}</strong>.</p>

<h2>2. Qué datos guardamos</h2>
<ul>
  <li>Tu número de WhatsApp y el nombre de tu perfil.</li>
  <li>Lo que anotás en el asistente: tareas, animales, lotes, establecimientos, productos, fechas y cantidades.</li>
  <li>Tus últimos mensajes con el asistente (los más recientes, para entender tus respuestas cortas). Se reemplazan solos a medida que escribís.</li>
  <li>La cantidad de mensajes que mandás por día, para aplicar el límite de uso.</li>
  <li>El identificador técnico que WhatsApp le asigna a cada mensaje, durante 7 días, para no procesar dos veces el mismo mensaje. Después se borra solo.</li>
</ul>
<p>Los audios se transcriben a texto y <strong>no se guardan</strong>. No pedimos ni guardamos datos de salud,
datos bancarios, documentos de identidad ni tu ubicación.</p>

<h2>3. Para qué los usamos</h2>
<ul>
  <li>Para guardar lo que anotás y mostrártelo cuando lo consultás, corregís o borrás.</li>
  <li>Para controlar quién tiene acceso al asistente y evitar abusos.</li>
</ul>
<p>No usamos tus datos para publicidad, no los vendemos y no armamos perfiles comerciales.</p>

<h2>4. Quién más ve tus datos</h2>
<p><strong>Ningún otro usuario.</strong> Tu cuaderno es personal: ni siquiera el dueño o encargado de un
campo puede ver lo que vos anotaste sobre ese campo.</p>
<p>Para funcionar, el asistente usa estos proveedores, que tratan los datos solo para prestar el servicio:</p>
<ul>
  <li><strong>Meta (WhatsApp Business Platform)</strong>: transporta tus mensajes entre tu celular y el asistente.</li>
  <li><strong>Groq, Inc.</strong>: interpreta el texto de tus mensajes y transcribe tus audios con inteligencia artificial.</li>
  <li><strong>El proveedor de servidores y base de datos</strong> donde está alojado el asistente.</li>
</ul>
<p>Algunos de estos proveedores están fuera de la Argentina (por ejemplo, en Estados Unidos). Al usar el
asistente aceptás esa transferencia internacional de datos, que se hace solo para prestarte el servicio.</p>

<h2>5. Precios y productos veterinarios</h2>
<p>Los precios que muestra el asistente son valores de referencia publicados por fuentes oficiales o
mercados regulados, con su fuente y fecha. La información de productos veterinarios proviene del registro
público de SENASA. Nada de esto es una recomendación de compra, venta, uso o tratamiento.</p>

<h2>6. Cuánto tiempo guardamos tus datos</h2>
<p>Mientras uses el asistente. Podés borrar registros puntuales cuando quieras, y si borrás tus datos
(ver punto 7) se eliminan todos de forma definitiva. Los identificadores técnicos de los mensajes se borran
solos a los 7 días.</p>

<h2>7. Tus derechos</h2>
<p>Según la Ley 25.326 de Protección de Datos Personales tenés derecho a acceder, rectificar, actualizar y
suprimir tus datos. Podés hacerlo desde el mismo chat:</p>
<ul>
  <li><strong>Ver tus datos</strong>: mandá <code>¿qué tengo anotado?</code></li>
  <li><strong>Corregirlos</strong>: decile qué cambiar, por ejemplo <code>no eran 20, eran 25</code>.</li>
  <li><strong>Borrar registros</strong>: por ejemplo <code>borrá la lluvia de La Pastora</code>.</li>
  <li><strong>Borrar todo, incluido tu número</strong>: mandá <code>borrar mis datos</code> y confirmá.</li>
</ul>
<p>También podés pedirlo escribiendo a {contacto}. Respondemos los pedidos de acceso dentro de los 10 días
corridos y los de rectificación o supresión dentro de los 5 días hábiles.</p>

<h2>8. Seguridad</h2>
<p>Solo pueden usar el asistente los números habilitados por el administrador. Los mensajes llegan
verificados por Meta, la comunicación viaja cifrada (HTTPS) y el acceso a la base de datos está restringido.</p>

<h2>9. Menores de edad</h2>
<p>El asistente está pensado para personas que trabajan en el campo y no está dirigido a menores de 18 años.</p>

<h2>10. Cambios a esta política</h2>
<p>Si cambiamos esta política, actualizamos la fecha de arriba y lo avisamos por el asistente cuando el
cambio sea importante.</p>

<div class="legal">
<p>El titular de los datos personales tiene la facultad de ejercer el derecho de acceso a los mismos en forma
gratuita a intervalos no inferiores a seis meses, salvo que se acredite un interés legítimo al efecto conforme
lo establecido en el artículo 14, inciso 3 de la Ley N° 25.326.</p>
<p>La AGENCIA DE ACCESO A LA INFORMACIÓN PÚBLICA, en su carácter de Órgano de Control de la Ley N° 25.326,
tiene la atribución de atender las denuncias y reclamos que interpongan quienes resulten afectados en sus
derechos por incumplimiento de las normas vigentes en materia de protección de datos personales.</p>
</div>
</main>
</body>
</html>
"""


def html() -> str:
    return _PLANTILLA.format(
        fecha=ULTIMA_ACTUALIZACION,
        responsable=escape(config.privacidad_responsable or "[completar PRIVACIDAD_RESPONSABLE]"),
        contacto=escape(config.privacidad_contacto or "[completar PRIVACIDAD_CONTACTO]"),
    )
