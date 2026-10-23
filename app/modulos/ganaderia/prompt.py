"""Lo que el módulo ganadero le suma al prompt: el tacto (paso 3 de la etapa 2). Raspaje y
sanidad llegan en los pasos 4 y 5.

Corto a propósito: el prompt del veterinario tiene un tope de 30.000 caracteres
(`modulos.LARGO_MAXIMO_PROMPT`) y tiene que entrar todo ganadería."""

from app.ia.prompt import Parte

PROMPT = Parte(
    intenciones=("tacto",),
    campos='  "tacto": TACTO | null            // solo si intencion = "tacto"',
    descripciones="""\
- "tacto": dicta RESULTADOS de un tacto o ecografía: vaca por vaca ("213 preñada cabeza CC 3, 214
  vacía, 215 cola") o el cierre de un lote ("88 preñadas: 60 cabeza, 20 cuerpo, 8 cola; 14 vacías,
  CC 3.2"). Corregir una vaca ("la 214 no, estaba preñada") es "tacto" con esa vaca de nuevo. Si
  solo cuenta que hizo tacto, sin resultados ("ayer hice tacto a 50 vaquillonas"), es "registrar"
  como cualquier evento, con su FECHA; si avisa que empieza ("arrancamos tacto en La Pastora"),
  "abrir_sesion".""",
    pedidos="""\
Las vacas y el cierre de un mensaje van en UNA acción "tacto". Si además dice que terminó
("Terminamos lote vaquillonas San Pedro: 88 preñadas…"), van el "tacto" y después el "cerrar_sesion".
Si empieza y ya dicta vacas ("arrancamos tacto en La Pastora, la primera la 101 preñada cabeza"),
van el "abrir_sesion" (sin lote: "la primera" es la vaca) y después el "tacto".""",
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
}""",
    reglas="""\
- En "tacto" NO calcules nada (ni el total, ni porcentajes, ni la suma de cabeza, cuerpo y cola):
  copiá los números que dice. "CC" es la condición corporal.
- "Lote vaquillonas San Pedro": vaquillonas es "categoria_animal", San Pedro el "establecimiento"
  y "lote" null. Si después de "lote" viene una categoría de hacienda, no es un lote.""",
)
