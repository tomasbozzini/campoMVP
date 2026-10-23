"""Lo que el módulo ganadero le suma al prompt: el tacto y el raspaje (pasos 3 y 4 de la etapa
2). Sanidad llega en el paso 5.

Corto a propósito: el prompt del veterinario tiene un tope de 30.000 caracteres
(`modulos.LARGO_MAXIMO_PROMPT`) y tiene que entrar todo ganadería."""

from app.ia.prompt import Parte

PROMPT = Parte(
    intenciones=("tacto", "raspaje"),
    campos=(
        '  "tacto": TACTO | null            // solo si intencion = "tacto"\n'
        '  "raspaje": RASPAJE | null        // solo si intencion = "raspaje"'
    ),
    descripciones="""\
- "tacto": dicta RESULTADOS de un tacto o ecografía: vaca por vaca ("213 preñada cabeza CC 3, 214
  vacía, 215 cola") o el cierre de un lote ("88 preñadas: 60 cabeza, 20 cuerpo, 8 cola; 14 vacías,
  CC 3.2"). Corregir una vaca ("la 214 no, estaba preñada") es "tacto" con esa vaca de nuevo. Si
  solo cuenta que hizo tacto, sin resultados ("ayer hice tacto a 50 vaquillonas"), es "registrar"
  como cualquier evento, con su FECHA; si avisa que empieza ("arrancamos tacto en La Pastora"),
  "abrir_sesion".
- "raspaje": raspaje de toros (tricomoniasis, campylobacter) con cada toro por su caravana o RP:
  el resultado, o que espera el del laboratorio ("Toro caravana 405 raspaje negativo, el 412
  dudoso, repetir en 15 días"). El resultado que llega del laboratorio de muestras ya tomadas
  ("llegó el del 412: negativo") también, con "laboratorio": true. "raspaje" lleva siempre algún
  toro con su caravana o RP: si cuenta que raspó sin nombrar ningún toro ("raspamos 12 toros en La
  Pastora"; "ayer raspamos los toros", con "fecha_evento": {"dias": -1}), es "registrar" como
  cualquier evento. Que tiene que repetir un raspaje, sin resultados ("en 15 días tengo que
  repetir el raspaje de los toros"), es "anotar_pendiente".""",
    pedidos="""\
Las vacas y el cierre de un mensaje van en UNA acción "tacto". Si además dice que terminó
("Terminamos lote vaquillonas San Pedro: 88 preñadas…"), van el "tacto" y después el "cerrar_sesion".
Si empieza y ya dicta vacas ("arrancamos tacto en La Pastora, la primera la 101 preñada cabeza"),
van el "abrir_sesion" (sin lote: "la primera" es la vaca) y después el "tacto".
Los toros de un mensaje van en UNA acción "raspaje".""",
    formatos="""\
TACTO:
{
  "vacas": [ { "caravana": string | null, "resultado": "prenada" | "vacia" | null,
               "estadio": "cabeza" | "cuerpo" | "cola" | null, "cc": number | null }, ... ],
                                // una por vaca que dicta, en orden; [] si no dicta vacas
  "cierre": { "prenadas": int | null, "cabeza": int | null, "cuerpo": int | null, "cola": int | null,
              "vacias": int | null, "total": int | null, "cc": number | null } | null,  // los números del lote
  "categoria_animal": string | null,  // como en EVENTO
  "lote": string | null,              // como en EVENTO
  "fecha_evento": FECHA | null
}

RASPAJE:
{
  "toros": [ { "caravana": string | null, "rp": string | null,  // "RP 412" -> rp; "el 412" -> caravana
               "resultado": "negativo" | "positivo" | "dudoso" | null,  // null: sin resultado todavía
               "enfermedad": "tricomoniasis" | "campylobacter" | null,  // null: las dos o no dice
               "muestreo": int | null,      // solo si dice cuál: "segundo raspaje" -> 2
               "repetir_en": string | null  // solo si lo dice, como lo dice: "15 días", "2 semanas"
             }, ... ],  // uno por toro (con resultados distintos por enfermedad, uno por cada una); nunca []
  "laboratorio": bool,
  "lote": string | null,
  "fecha_evento": FECHA | null
}""",
    reglas="""\
- En "tacto" NO calcules nada (ni el total, ni porcentajes, ni la suma de cabeza, cuerpo y cola):
  copiá los números que dice. "CC" es la condición corporal.
- "Lote vaquillonas San Pedro": vaquillonas es "categoria_animal", San Pedro el "establecimiento"
  y "lote" null. Si después de "lote" viene una categoría de hacienda, no es un lote.
- En CONSULTA, los raspajes son "tipo": "raspaje".""",
)
