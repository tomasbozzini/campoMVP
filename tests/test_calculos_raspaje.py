"""Las cuentas del raspaje: el número de muestreo y la fecha para repetir."""

from datetime import date

import pytest

from app.calculos.raspaje import fecha_para_repetir, muestreo

DIA = date(2026, 10, 13)


def test_el_primer_raspaje_es_el_1():
    assert muestreo([], DIA) == 1


@pytest.mark.parametrize(
    ("anteriores", "fecha", "esperado"),
    [
        ([(date(2026, 9, 28), 1)], DIA, 2),
        ([(date(2026, 9, 28), 1), (date(2026, 10, 5), 2)], DIA, 3),
        ([(date(2026, 8, 14), 1)], DIA, 2),  # 60 días justos: sigue
        ([(date(2026, 8, 13), 1)], DIA, 1),  # 61: otra serie
        ([(date(2025, 10, 13), 3)], DIA, 1),  # el del año pasado
        ([(date(2026, 10, 20), 1)], DIA, 1),  # uno posterior no cuenta
        ([(date(2026, 10, 1), 4)], DIA, 5),  # sigue desde el número que quedó, aunque lo haya dicho
    ],
)
def test_el_muestreo_sigue_la_serie_de_60_dias(anteriores, fecha, esperado):
    assert muestreo(anteriores, fecha) == esperado


@pytest.mark.parametrize(
    ("intervalo", "esperada"),
    [
        ("15 días", date(2026, 10, 28)),  # el ejemplo de la especificación
        ("en 15 dias", date(2026, 10, 28)),
        ("quince días", date(2026, 10, 28)),
        ("15", date(2026, 10, 28)),
        ("2 semanas", date(2026, 10, 27)),
        ("una semana", date(2026, 10, 20)),
        ("un mes", date(2026, 11, 13)),
        ("3 meses", date(2027, 1, 13)),
    ],
)
def test_la_fecha_para_repetir_la_calcula_el_codigo(intervalo, esperada):
    assert fecha_para_repetir(DIA, intervalo) == esperada


def test_un_mes_desde_el_31_cae_en_el_ultimo_dia():
    assert fecha_para_repetir(date(2027, 1, 31), "un mes") == date(2027, 2, 28)


@pytest.mark.parametrize("intervalo", [None, "", "pronto", "cuando llegue el resultado", "0 días", "2 años", "400"])
def test_lo_que_no_es_un_intervalo_no_da_fecha(intervalo):
    assert fecha_para_repetir(DIA, intervalo) is None
