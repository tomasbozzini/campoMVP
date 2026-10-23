"""python -m app eval: el set de evaluación contra la IA (acá, una falsa)."""

from datetime import date

import pytest

from app import modulos, terminal
from app.ia import evaluacion, proveedor
from app.ia.evaluacion import Frase
from app.ia.proveedor import IASaturada, Uso
from app.infra.config import config
from app.nucleo import acciones

HOY = date(2026, 10, 16)
FRASES = [
    Frase("mis_campos", "quiero ver mis campos", ("mis_campos",)),
    Frase("ayuda", "¿qué podés hacer?", ("ayuda",)),
    Frase("varios", "mis campos y pendientes", ("mis_campos", "ver_pendientes")),
    Frase("ayuda", "mandame el menú", ("ayuda",)),
]


class IAFalsa:
    """Responde según la frase, anota el uso como un proveedor real y cuenta los pedidos."""

    def __init__(self, respuestas: dict[str, object], costo: float | None = 0.01) -> None:
        self.respuestas = respuestas
        self.costo = costo
        self.pedidos: list[str] = []

    def completar_json(self, sistema: str, mensaje: str) -> object:
        frase = mensaje.removeprefix("<<<MENSAJE\n").removesuffix("\nMENSAJE>>>")
        self.pedidos.append(frase)
        respuesta = self.respuestas.get(frase, {"acciones": []})
        if isinstance(respuesta, Exception):
            raise respuesta
        proveedor.anotar_uso(Uso("falsa", None, 5000, 100 * len(self.pedidos), 50, self.costo, 0.0))
        return respuesta


BIEN = {
    "quiero ver mis campos": {"acciones": [{"intencion": "mis_campos"}]},
    "¿qué podés hacer?": {"intencion": "ayuda"},  # una sola acción, sin la lista: el núcleo la acepta
    "mis campos y pendientes": {"acciones": [{"intencion": "ver_pendientes"}, {"intencion": "mis_campos"}]},
    "mandame el menú": IASaturada("OpenRouter 429"),
}


def test_el_set_se_lee_entero():
    frases = evaluacion.cargar()
    assert len(frases) >= 80 and all(f.frase and f.intenciones for f in frases)


def test_se_puede_correr_una_parte():
    assert evaluacion.elegir(FRASES, ["ayuda"]) == [FRASES[1], FRASES[3]]
    assert evaluacion.elegir(FRASES, desde=2, limite=2) == FRASES[1:3]
    assert evaluacion.elegir(FRASES, ["ayuda"], desde=2) == [FRASES[3]]
    assert evaluacion.elegir(FRASES, ["inventada"]) == []


def test_compara_las_intenciones_en_orden_y_mide_todo():
    ia = IAFalsa(BIEN)
    resultados, frenado = evaluacion.correr(FRASES, ia, [], HOY, tope_usd=1.0)
    assert not frenado and len(ia.pedidos) == 4
    assert [r.bien for r in resultados] == [True, True, False, False]  # otro orden; un error
    assert resultados[3].error == "OpenRouter 429"

    r = evaluacion.resumir(resultados)
    assert (r.total, r.bien, r.errores) == (4, 2, 1)
    assert (r.tokens_entrada, r.tokens_salida, r.tokens_razonamiento) == (15000, 600, 150)
    assert r.costo_usd == pytest.approx(0.03) and r.precision == 0.5


def test_una_frase_puede_aceptar_otras_respuestas():
    """Paso 9.1: "quiero ver" está bien como aclarar o como consultar (mostrar no hace daño)."""
    frase = evaluacion.Frase("ambiguo", "quiero ver", ("aclarar",), o_bien=(("consultar",),))
    assert frase.acepta(("aclarar",)) and frase.acepta(("consultar",))
    assert not frase.acepta(("borrar",)) and not frase.acepta(("aclarar", "consultar"))
    del_set = next(f for f in evaluacion.cargar() if f.frase == "quiero ver")
    assert del_set.o_bien == (("consultar",),)
    resultados = [evaluacion.Resultado(frase, obtenidas=("consultar",)), evaluacion.Resultado(frase, obtenidas=())]
    assert evaluacion.por_funcion(resultados) == {"ambiguo": (1, 2)}


def test_frena_al_llegar_al_tope_de_costo():
    ia = IAFalsa(BIEN, costo=0.2)
    resultados, frenado = evaluacion.correr(FRASES, ia, [], HOY, tope_usd=0.35)
    assert frenado and len(resultados) == 2 and len(ia.pedidos) == 2


def test_sin_costo_informado_no_inventa_uno():
    resultados, _ = evaluacion.correr(FRASES[:1], IAFalsa(BIEN, costo=None), [], HOY, tope_usd=0.5)
    assert evaluacion.resumir(resultados).costo_usd is None


def test_mediana_y_p95_de_la_demora():
    resultados = [evaluacion.Resultado(FRASES[0], segundos=s) for s in [float(i) for i in range(1, 21)]]
    r = evaluacion.resumir(resultados)
    assert (r.mediana, r.p95) == (10.5, 19.0)


class IAQueGuarda:
    def __init__(self) -> None:
        self.mensajes: list[str] = []

    def completar_json(self, sistema: str, mensaje: str) -> object:
        self.mensajes.append(mensaje)
        return {"acciones": [{"intencion": "cancelar"}]}


def test_una_frase_puede_traer_la_charla_reciente_y_la_pregunta_pendiente(tmp_path):
    ruta = tmp_path / "set.json"
    ruta.write_text(
        '{"frases": [{"funcion": "cancelar", "frase": "no, dejá", "intenciones": ["cancelar"],'
        ' "historial": [["usuario", "cambiar rubro"], ["bot", "¿A qué te dedicás?"]], "pregunta": "rubro"}]}',
        encoding="utf-8",
    )
    [frase] = evaluacion.cargar(ruta)
    assert (
        frase.historial == (("usuario", "cambiar rubro"), ("bot", "¿A qué te dedicás?")) and frase.pregunta == "rubro"
    )

    ia = IAQueGuarda()
    resultados, _ = evaluacion.correr([frase], ia, [], HOY, tope_usd=1.0, preguntas={"rubro": "¿A qué te dedicás?"})
    assert resultados[0].bien
    assert ia.mensajes == [
        "<<<CONVERSACION_RECIENTE\nPersona: cambiar rubro\nSistema: ¿A qué te dedicás?\nCONVERSACION_RECIENTE>>>\n\n"
        "<<<PREGUNTA_PENDIENTE\n¿A qué te dedicás?\nPREGUNTA_PENDIENTE>>>\n\n<<<MENSAJE\nno, dejá\nMENSAJE>>>"
    ]


def test_el_comando_eval_muestra_cada_frase_y_el_resumen(monkeypatch, capsys):
    modulos.cargar()
    ia = IAFalsa(BIEN)
    pedido: dict = {}

    def uno_solo(nombre, esfuerzo=None):
        pedido.update(nombre=nombre, esfuerzo=esfuerzo)
        return ia

    monkeypatch.setattr(config, "openrouter_api_key", "clave-or")
    monkeypatch.setattr(proveedor, "uno_solo", uno_solo)
    monkeypatch.setattr(evaluacion, "cargar", lambda: FRASES)
    terminal.main(["eval", "--funcion", "ayuda", "--esfuerzo", "low"])

    salida = capsys.readouterr().out
    assert pedido == {"nombre": "openrouter", "esfuerzo": "low"}
    assert ia.pedidos == ["¿qué podés hacer?", "mandame el menú"]
    assert "2 frases contra openrouter (esfuerzo low)" in salida
    assert "✓" in salida and "error: OpenRouter 429" in salida
    for dato in ("Precisión: 1/2 (50%)", "Llamadas: 2 (1 con error)", "Tokens: 5000 de entrada", "Costo: USD 0.0100"):
        assert dato in salida
    assert "Demora: mediana" in salida and "p95" in salida
    assert "Nombres casi iguales corregidos: 0" in salida


def test_el_comando_eval_muestra_los_nombres_casi_iguales(monkeypatch, capsys):
    modulos.cargar()
    ia = IAFalsa({"¿qué podés hacer?": {"intencion": "ayudas"}})
    monkeypatch.setattr(config, "openrouter_api_key", "clave-or")
    monkeypatch.setattr(proveedor, "uno_solo", lambda _nombre, _esfuerzo=None: ia)
    monkeypatch.setattr(evaluacion, "cargar", lambda: FRASES[1:2])
    terminal.main(["eval"])
    salida = capsys.readouterr().out
    assert "nombre casi igual: vino 'ayudas' y se tomó como 'ayuda'" in salida
    assert "Precisión: 1/1" in salida and "Nombres casi iguales corregidos: 1" in salida


def test_eval_sin_clave_avisa(monkeypatch):
    monkeypatch.setattr(config, "openrouter_api_key", "")
    with pytest.raises(SystemExit, match="OPENROUTER_API_KEY"):
        terminal.main(["eval", "--proveedor", "openrouter"])


def test_controla_las_fechas_que_quedan_con_el_hoy_de_la_frase():
    """La fecha que queda la calcula el código con el "hoy" de la frase, como en el bot."""
    modulos.cargar()
    martes = date(2026, 10, 20)
    frases = [
        Frase("fecha", "tenía que pagar el sábado", ("anotar_pendiente",), hoy=martes, fechas=("2026-10-17",)),
        Frase("fecha", "tengo que pagar el sábado", ("anotar_pendiente",), hoy=martes, fechas=("2026-10-17",)),
        Frase("fecha", "el viernes 22 pago", ("anotar_pendiente",), hoy=martes, fechas=("dudosa",)),
    ]

    def pendiente(vence: dict) -> dict:
        return {"intencion": "anotar_pendiente", "pendiente": {"texto": "pagar", "vence": vence}}

    ia = IAFalsa(
        {
            "tenía que pagar el sábado": pendiente({"dia_semana": "sabado", "cual": "pasado"}),
            "tengo que pagar el sábado": pendiente({"dia_semana": "sabado"}),
            "el viernes 22 pago": pendiente({"dia_semana": "viernes", "dia": 22}),
        }
    )
    resultados, _ = evaluacion.correr(frases, ia, [], HOY, tope_usd=1.0, fechas=acciones.fechas)
    assert [r.fechas for r in resultados] == [("2026-10-17",), ("2026-10-24",), ("dudosa",)]
    assert [r.bien for r in resultados] == [True, False, True]


def test_las_frases_con_fechas_del_set_tienen_hoy():
    frases = [f for f in evaluacion.cargar() if f.fechas is not None]
    assert frases and all(f.hoy is not None for f in frases)
