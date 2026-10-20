"""Las fechas las calcula el código (paso 8.5.1 del plan): la IA devuelve lo que dijo la persona
(FECHA) y `ia/fechas.py` la convierte con la fecha de hoy. Sin IA."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.ia import fechas, interprete
from app.ia.fechas import PASADO, PROXIMO, Dicha, FechaDudosa
from app.infra.modelos import Evento, Pendiente
from app.modulos.comun.consultar import FiltrosConsulta
from app.modulos.comun.pendientes import DatosPendiente
from app.modulos.comun.registros import DatosEvento
from app.nucleo import pipeline, respuestas
from app.salidas.whatsapp import fecha_corta
from tests.ayudas import con_perfil

MARTES = date(2026, 10, 20)  # el día de la prueba desde el celular
TEL = "5491100000001"
AHORA = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
# Una semana entera, de lunes a domingo, para probar "hoy" en cada día.
SEMANA = [date(2026, 10, 19) + timedelta(days=n) for n in range(7)]


def _calcular(dicha: dict, hoy: date = MARTES, sentido: str = PASADO) -> date | None:
    leida = fechas.leer(dicha)
    assert leida is not None
    return fechas.calcular(leida, hoy, sentido)


# --- Lo que falló en la prueba -----------------------------------------------------------


def test_las_tres_frases_de_la_prueba():
    # "Tenía que pagarle al contratista el sábado": el sábado pasado, vencido.
    assert _calcular({"dia_semana": "sabado", "cual": "pasado"}, sentido=PROXIMO) == date(2026, 10, 17)
    # "El sábado pasado tenía que pagarle al contratista"
    assert _calcular({"dia_semana": "sábado", "cual": "pasado"}, sentido=PROXIMO) == date(2026, 10, 17)
    # "Y el sábado que viene le tengo que pagar al contratista"
    assert _calcular({"dia_semana": "sabado", "cual": "proximo"}, sentido=PROXIMO) == date(2026, 10, 24)


# --- Días de la semana -------------------------------------------------------------------


@pytest.mark.parametrize("hoy", SEMANA, ids=[fechas.DIAS[d.weekday()] for d in SEMANA])
@pytest.mark.parametrize("dia", fechas.DIAS)
def test_cada_dia_de_la_semana_desde_cada_dia(hoy, dia):
    """El pasado es el más reciente antes de hoy y el próximo el primero después: entre 1 y 7
    días, con el día de la semana pedido. Nunca hoy."""
    pasado = _calcular({"dia_semana": dia, "cual": "pasado"}, hoy)
    proximo = _calcular({"dia_semana": dia, "cual": "proximo"}, hoy)
    assert pasado is not None and proximo is not None
    assert fechas.DIAS[pasado.weekday()] == dia == fechas.DIAS[proximo.weekday()]
    assert 1 <= (hoy - pasado).days <= 7 and 1 <= (proximo - hoy).days <= 7


def test_el_sabado_dicho_un_sabado_es_hace_7_dias_o_dentro_de_7():
    sabado = date(2026, 10, 17)
    assert _calcular({"dia_semana": "sabado", "cual": "pasado"}, sabado) == date(2026, 10, 10)
    assert _calcular({"dia_semana": "sabado", "cual": "proximo"}, sabado) == date(2026, 10, 24)


def test_sin_decir_cual_manda_el_sentido_del_dato():
    """Los registros y las consultas miran para atrás; los pendientes, para adelante."""
    assert _calcular({"dia_semana": "jueves"}, sentido=PASADO) == date(2026, 10, 15)
    assert _calcular({"dia_semana": "jueves"}, sentido=PROXIMO) == date(2026, 10, 22)


def test_los_dias_de_la_semana_cruzan_el_mes_y_el_anio():
    assert _calcular({"dia_semana": "lunes", "cual": "proximo"}, date(2026, 10, 30)) == date(2026, 11, 2)
    assert _calcular({"dia_semana": "viernes", "cual": "proximo"}, date(2026, 12, 30)) == date(2027, 1, 1)
    assert _calcular({"dia_semana": "domingo", "cual": "pasado"}, date(2027, 1, 2)) == date(2026, 12, 27)


# --- Días para atrás o para adelante -----------------------------------------------------


@pytest.mark.parametrize(
    ("dias", "esperada"),
    [
        (0, date(2026, 10, 20)),  # hoy
        (-1, date(2026, 10, 19)),  # ayer
        (-2, date(2026, 10, 18)),  # anteayer
        (1, date(2026, 10, 21)),  # mañana
        (-3, date(2026, 10, 17)),  # hace 3 días
        (21, date(2026, 11, 10)),  # en 21 días: cambia el mes
        (73, date(2027, 1, 1)),  # cambia el año
    ],
)
def test_dias_desde_hoy(dias, esperada):
    assert _calcular({"dias": dias}) == esperada


def test_los_dias_ganan_sobre_lo_demas():
    assert _calcular({"dias": -1, "dia_semana": "viernes"}) == date(2026, 10, 19)


# --- Día y mes ---------------------------------------------------------------------------


def test_solo_el_numero_es_el_mas_cercano_en_su_sentido():
    # Mirando para adelante: el 22 de este mes; el 15 ya pasó, es el del mes que viene.
    assert _calcular({"dia": 22}, sentido=PROXIMO) == date(2026, 10, 22)
    assert _calcular({"dia": 15}, sentido=PROXIMO) == date(2026, 11, 15)
    # Mirando para atrás ("tenía que pagar el 22"): el del mes pasado.
    assert _calcular({"dia": 22, "cual": "pasado"}, sentido=PROXIMO) == date(2026, 9, 22)
    assert _calcular({"dia": 15}, sentido=PASADO) == date(2026, 10, 15)
    # Hoy cuenta para los dos sentidos.
    assert _calcular({"dia": 20}, sentido=PASADO) == _calcular({"dia": 20}, sentido=PROXIMO) == MARTES


def test_solo_el_numero_cruza_el_mes_y_el_anio():
    assert _calcular({"dia": 5}, date(2026, 12, 28), PROXIMO) == date(2027, 1, 5)
    assert _calcular({"dia": 30}, date(2027, 1, 3), PASADO) == date(2026, 12, 30)
    # El 31 no está en noviembre: mirando para adelante desde el 20/11 es el 31/12.
    assert _calcular({"dia": 31}, date(2026, 11, 20), PROXIMO) == date(2026, 12, 31)


def test_dia_y_mes_para_atras_es_el_mas_reciente_que_no_es_despues_de_hoy():
    """Registros y consultas (paso 8.5.2): cargar cosas viejas del cuaderno."""
    # "El 5 de marzo nacieron 3 terneros": este año, no el que viene.
    assert _calcular({"dia": 5, "mes": 3}) == date(2026, 3, 5)
    # "desde el 1 de marzo"
    assert _calcular({"dia": 1, "mes": 3}) == date(2026, 3, 1)
    # Un día después de hoy ya es del año pasado; hoy es hoy.
    assert _calcular({"dia": 21, "mes": 10}) == date(2025, 10, 21)
    assert _calcular({"dia": 20, "mes": 10}) == MARTES
    assert _calcular({"dia": 20, "mes": 4}) == date(2026, 4, 20)
    # Cambio de año: "el 28 de diciembre" dicho el 2 de enero.
    assert _calcular({"dia": 28, "mes": 12}, date(2027, 1, 2)) == date(2026, 12, 28)
    # El 29 de febrero, del último año bisiesto.
    assert _calcular({"dia": 29, "mes": 2}, date(2027, 6, 1)) == date(2024, 2, 29)


def test_dia_y_mes_con_pasado_o_proximo_dicho():
    # Un "pasado" dicho en un pendiente mira para atrás.
    assert _calcular({"dia": 25, "mes": 10, "cual": "pasado"}, sentido=PROXIMO) == date(2025, 10, 25)
    assert _calcular({"dia": 5, "mes": 3, "cual": "pasado"}, sentido=PROXIMO) == date(2026, 3, 5)
    # Un "próximo" dicho: el primero que no sea antes de hoy.
    assert _calcular({"dia": 15, "mes": 10, "cual": "proximo"}) == date(2027, 10, 15)
    assert _calcular({"dia": 20, "mes": 10, "cual": "proximo"}) == MARTES
    # "el 3 de enero que viene" dicho el 20 de diciembre
    assert _calcular({"dia": 3, "mes": 1, "cual": "proximo"}, date(2026, 12, 20)) == date(2027, 1, 3)


def test_dia_y_mes_en_un_pendiente_sin_decir_cual_es_el_mas_cercano():
    assert _calcular({"dia": 5, "mes": 11}, sentido=PROXIMO) == date(2026, 11, 5)
    assert _calcular({"dia": 28, "mes": 9}, sentido=PROXIMO) == date(2026, 9, 28)  # ya pasó: vencido
    assert _calcular({"dia": 15, "mes": 10}, sentido=PROXIMO) == date(2026, 10, 15)
    # "el 3 de enero" dicho el 20 de diciembre es del año que viene.
    assert _calcular({"dia": 3, "mes": 1}, date(2026, 12, 20), PROXIMO) == date(2027, 1, 3)


def test_con_el_anio_es_esa_fecha():
    assert _calcular({"dia": 5, "mes": 11, "anio": 2025}, sentido=PROXIMO) == date(2025, 11, 5)
    assert _calcular({"dia": 5, "mes": 11, "anio": 2027}) == date(2027, 11, 5)


def test_un_dia_que_no_existe_no_es_una_fecha():
    assert _calcular({"dia": 31, "mes": 11}) is None
    assert _calcular({"dia": 29, "mes": 2, "anio": 2026}) is None


def test_dia_de_la_semana_y_numero_que_coinciden():
    assert _calcular({"dia_semana": "jueves", "dia": 22}, sentido=PROXIMO) == date(2026, 10, 22)
    assert _calcular({"dia_semana": "jueves", "dia": 22, "mes": 10}, sentido=PROXIMO) == date(2026, 10, 22)
    assert _calcular({"dia_semana": "jueves", "dia": 15, "mes": 10}) == date(2026, 10, 15)


def test_dia_de_la_semana_y_numero_que_no_coinciden_es_dudosa():
    with pytest.raises(FechaDudosa) as dudosa:
        _calcular({"dia_semana": "viernes", "dia": 22}, sentido=PROXIMO)
    # El 22 (jueves) y el viernes más cercano al 22.
    assert dudosa.value.opciones == (date(2026, 10, 22), date(2026, 10, 23))
    with pytest.raises(FechaDudosa) as dudosa:
        _calcular({"dia_semana": "lunes", "dia": 22}, sentido=PROXIMO)
    assert dudosa.value.opciones == (date(2026, 10, 22), date(2026, 10, 19))
    # Ya respondida, es la que eligió.
    leida = fechas.leer({"dia_semana": "viernes", "dia": 22})
    assert leida is not None
    elegida = fechas.calcular(leida, MARTES, PROXIMO, {leida.clave: "2026-10-23"})
    assert elegida == date(2026, 10, 23)


@pytest.mark.parametrize(
    "valor",
    [None, "ayer", "2026-10-20", 3, [], {}, {"dia_semana": "feriado"}, {"dias": "muchos"}, {"dias": 5000}, {"mes": 11}],
)
def test_lo_que_no_es_una_fecha_queda_vacio(valor):
    """Un texto no es una FECHA: la IA no calcula fechas. Solo el mes no dice qué día."""
    assert fechas.leer(valor) is None


def test_los_datos_raros_se_ignoran():
    assert fechas.leer({"dia_semana": "Miércoles", "cual": "que viene", "dia": 40, "anio": 1990}) == Dicha(dia_semana=2)
    assert fechas.leer({"dias": True}) is None  # true no es un número


# --- En los esquemas -------------------------------------------------------------------


def test_los_esquemas_calculan_con_el_hoy_que_les_pasan():
    contexto = {"hoy": MARTES}
    evento = DatosEvento.model_validate({"fecha_evento": {"dia_semana": "sabado"}}, context=contexto)
    pendiente = DatosPendiente.model_validate({"vence": {"dia_semana": "sabado"}}, context=contexto)
    assert evento.fecha_evento == date(2026, 10, 17) and pendiente.vence == date(2026, 10, 24)


@pytest.mark.parametrize(
    ("periodo", "desde", "hasta"),
    [
        ("hoy", date(2026, 10, 20), date(2026, 10, 20)),
        ("ayer", date(2026, 10, 19), date(2026, 10, 19)),
        ("esta_semana", date(2026, 10, 19), date(2026, 10, 20)),
        ("semana_pasada", date(2026, 10, 12), date(2026, 10, 18)),
        ("este_mes", date(2026, 10, 1), date(2026, 10, 20)),
        ("mes_pasado", date(2026, 9, 1), date(2026, 9, 30)),
        ("este_anio", date(2026, 1, 1), date(2026, 10, 20)),
        ("anio_pasado", date(2025, 1, 1), date(2025, 12, 31)),
    ],
)
def test_los_periodos_de_las_consultas(periodo, desde, hasta):
    filtros = FiltrosConsulta.model_validate({"periodo": periodo}, context={"hoy": MARTES})
    assert (filtros.desde, filtros.hasta) == (desde, hasta)


def test_meses_y_rangos_de_las_consultas():
    def rango(datos: dict, hoy: date = MARTES) -> tuple[date | None, date | None]:
        filtros = FiltrosConsulta.model_validate(datos, context={"hoy": hoy})
        return filtros.desde, filtros.hasta

    assert rango({"mes": 9}) == (date(2026, 9, 1), date(2026, 9, 30))
    assert rango({"mes": 12}) == (date(2025, 12, 1), date(2025, 12, 31))  # todavía no llegó: el del año pasado
    assert rango({"mes": 2}, date(2028, 3, 5)) == (date(2028, 2, 1), date(2028, 2, 29))
    assert rango({"periodo": "mes_pasado"}, date(2027, 1, 10)) == (date(2026, 12, 1), date(2026, 12, 31))
    assert rango({"desde": {"dia_semana": "lunes"}}) == (date(2026, 10, 19), None)
    assert rango({"desde": {"dias": -10}}) == (date(2026, 10, 10), None)
    assert rango({"desde": {"dia": 1, "mes": 3}}) == (date(2026, 3, 1), None)  # no el de 2027
    assert rango({"periodo": "la quincena", "mes": 0}) == (None, None)


# --- La pregunta "¿Para cuándo?" ------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "elegida"),
    [
        ("1", 0),
        ("la 2", 1),
        ("opción 1", 0),
        ("el jueves", 0),
        ("viernes", 1),
        ("el 23", 1),
        ("Vie 23/10", 1),
        ("el 22 de octubre", 0),
        ("jue", 0),
        ("el viernes 22", None),  # no coincide con ninguna
        ("octubre", None),  # coincide con las dos
        ("vacuné 20 vacas", None),  # no es una respuesta
        ("", None),
    ],
)
def test_que_fecha_elige(texto, elegida):
    assert respuestas.cual_fecha(texto, [date(2026, 10, 22), date(2026, 10, 23)]) == elegida


PENDIENTE_DUDOSO = {
    "intencion": "anotar_pendiente",
    "establecimiento": "La Pastora",
    "pendiente": {"texto": "ir a vacunar", "vence": {"dia_semana": "viernes", "dia": 22}},
}


@pytest.fixture
def ia(monkeypatch):
    respuestas_ia: dict[str, object] = {
        "el viernes 22 tengo que ir a vacunar a la pastora": PENDIENTE_DUDOSO,
        "el viernes 15 vacuné 30 vacas": {
            "intencion": "registrar",
            "eventos": [
                {"categoria": "sanidad", "tipo": "vacunacion", "cantidad_animales": 30, "categoria_animal": "vacas"}
                | {"fecha_evento": {"dia_semana": "viernes", "dia": 15, "mes": 10}},
            ],
        },
        "no, dejá, después lo anoto": {"intencion": "cancelar"},
    }
    reloj = {"ahora": AHORA}
    monkeypatch.setattr(pipeline, "_ahora", lambda: reloj["ahora"])
    monkeypatch.setattr(interprete, "interpretar", lambda texto, *_a, **_k: respuestas_ia[texto])
    return respuestas_ia, reloj


def _mandar(db, texto):
    return pipeline.manejar_mensaje(db, TEL, texto, hoy=MARTES)


def _vencimientos(db) -> list[date | None]:
    return list(db.scalars(select(Pendiente.vence)))


def test_pregunta_para_cuando_y_no_anota_nada(db, ia):
    con_perfil(db, TEL)
    r = _mandar(db, "el viernes 22 tengo que ir a vacunar a la pastora")
    assert r.startswith("🤔 *¿Para cuándo?*\n\nEl 22/10 es jueves, no viernes.")
    assert "1️⃣ Jue 22/10/2026" in r and "2️⃣ Vie 23/10/2026" in r
    assert "Respondé *1* o *2*, o *cancelá*." in r
    assert _vencimientos(db) == []


@pytest.mark.parametrize(("respuesta", "fecha"), [("1", date(2026, 10, 22)), ("el viernes", date(2026, 10, 23))])
def test_con_la_respuesta_lo_anota_en_esa_fecha(db, ia, respuesta, fecha):
    con_perfil(db, TEL)
    _mandar(db, "el viernes 22 tengo que ir a vacunar a la pastora")
    r = _mandar(db, respuesta)
    assert r.startswith("📌 *PENDIENTE ANOTADO*") and fecha_corta(fecha) in r
    assert _vencimientos(db) == [fecha]


def test_un_registro_con_fecha_dudosa_tambien_pregunta(db, ia):
    con_perfil(db, TEL)
    r = _mandar(db, "el viernes 15 vacuné 30 vacas")
    assert r.startswith("🤔 *¿Para cuándo?*\n\nEl 15/10 es jueves, no viernes.") and "2️⃣ Vie 16/10/2026" in r
    assert _mandar(db, "el viernes").startswith("✅")
    assert [e.fecha_evento for e in db.scalars(select(Evento))] == [date(2026, 10, 16)]


def test_cancelar_o_no_no_anota_nada(db, ia):
    con_perfil(db, TEL)
    _mandar(db, "el viernes 22 tengo que ir a vacunar a la pastora")
    assert _mandar(db, "no") == "👌 Listo, no anoté nada."
    _mandar(db, "el viernes 22 tengo que ir a vacunar a la pastora")
    assert _mandar(db, "no, dejá, después lo anoto") == "👌 Listo, no anoté nada."  # por la IA
    assert _vencimientos(db) == []


def test_la_respuesta_vale_10_minutos(db, ia):
    _, reloj = ia
    con_perfil(db, TEL)
    _mandar(db, "el viernes 22 tengo que ir a vacunar a la pastora")
    reloj["ahora"] = AHORA + timedelta(minutes=11)
    assert _mandar(db, "2").startswith("⏱️ Pasó mucho tiempo")
    assert _vencimientos(db) == []


NACIMIENTO = {"categoria": "movimiento", "tipo": "nacimiento", "cantidad_animales": 3, "categoria_animal": "terneros"}


def test_un_registro_viejo_con_dia_y_mes_queda_en_su_fecha_y_se_corrige(db, ia):
    """Paso 8.5.2: "el 5 de marzo" quedaba en el año que viene y el registro, en hoy."""
    respuestas_ia, _ = ia
    respuestas_ia["el 5 de marzo nacieron 3 terneros"] = {
        "intencion": "registrar",
        "eventos": [NACIMIENTO | {"fecha_evento": {"dia": 5, "mes": 3}}],
    }
    respuestas_ia["nacieron 3 terneros"] = {"intencion": "registrar", "eventos": [NACIMIENTO]}
    respuestas_ia["ese nacimiento fue el 5 de marzo"] = {
        "intencion": "corregir",
        "correccion": {"referencia": {"tipo": "nacimiento"}, "cambios": {"fecha_evento": {"dia": 5, "mes": 3}}},
    }
    respuestas_ia["¿qué hice desde el 1 de marzo?"] = {
        "intencion": "consultar",
        "consulta": {"desde": {"dia": 1, "mes": 3}},
    }
    con_perfil(db, TEL)
    assert "Jue 05/03/2026" in _mandar(db, "el 5 de marzo nacieron 3 terneros")
    _mandar(db, "nacieron 3 terneros")  # quedó en hoy, como el registro de la prueba
    assert "05/03/2026" in _mandar(db, "ese nacimiento fue el 5 de marzo")
    assert [e.fecha_evento for e in db.scalars(select(Evento))] == [date(2026, 3, 5), date(2026, 3, 5)]
    assert "2 registros" in _mandar(db, "¿qué hice desde el 1 de marzo?")
