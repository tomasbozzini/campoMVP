"""Las cuentas del tacto (`app/calculos/tacto.py`): las hace el código, nunca la IA."""

import pytest

from app.calculos import tacto
from app.calculos.tacto import PRENADA, VACIA, Diferencia, Vaca


def test_el_ejemplo_de_la_especificacion():
    """ "Terminamos lote vaquillonas San Pedro: 88 preñadas (60 cabeza, 20 cuerpo, 8 cola), 14
    vacías, CC 3.2". La especificación dice 86,2 %; 88 de 102 redondeado a un decimal es 86,3."""
    c = tacto.de_cierre(prenadas=88, cabeza=60, cuerpo=20, cola=8, vacias=14, cc=3.2)
    assert (c.prenadas, c.vacias, c.total, c.porcentaje, c.cc) == (88, 14, 102, 86.3, 3.2)
    assert c.estadios == {"cabeza": 60, "cuerpo": 20, "cola": 8} and c.diferencias == ()


def test_si_cabeza_cuerpo_y_cola_no_dan_las_prenadas_vale_lo_que_dijo_y_se_avisa():
    c = tacto.de_cierre(prenadas=88, cabeza=60, cuerpo=20, cola=6, vacias=14)
    assert (c.prenadas, c.total, c.porcentaje) == (88, 102, 86.3)
    assert c.diferencias == (Diferencia("cabeza, cuerpo y cola", 86, 88),)


def test_con_dos_de_las_tres_solo_se_avisa_si_se_pasan():
    assert tacto.de_cierre(prenadas=88, cabeza=60, cola=8, vacias=14).diferencias == ()
    assert tacto.de_cierre(prenadas=50, cabeza=40, cola=20).diferencias == (Diferencia("cabeza y cola", 60, 50),)


def test_si_solo_dice_cabeza_cuerpo_y_cola_las_prenadas_son_la_suma():
    c = tacto.de_cierre(cabeza=60, cuerpo=20, cola=8, vacias=14)
    assert (c.prenadas, c.total, c.porcentaje) == (88, 102, 86.3)


def test_con_el_total_se_calcula_el_que_falta():
    c = tacto.de_cierre(prenadas=25, total=30)
    assert (c.vacias, c.porcentaje) == (5, 83.3)
    assert tacto.de_cierre(vacias=5, total=30).prenadas == 25
    # Un total menor que las preñadas no sirve para calcular las vacías ni el porcentaje.
    c = tacto.de_cierre(prenadas=40, total=30)
    assert (c.vacias, c.porcentaje) == (None, None)


def test_si_prenadas_y_vacias_no_dan_el_total_se_avisa_y_vale_la_suma():
    c = tacto.de_cierre(prenadas=88, vacias=14, total=100)
    assert (c.total, c.porcentaje) == (102, 86.3)
    assert c.diferencias == (Diferencia("preñadas y vacías", 102, 100),)


def test_sin_vacias_ni_total_no_hay_porcentaje():
    c = tacto.de_cierre(prenadas=88, cc=3.25)
    assert (c.total, c.porcentaje, c.cc) == (None, None, 3.3)


@pytest.mark.parametrize(
    ("parte", "total", "esperado"),
    [(88, 102, 86.3), (1, 16, 6.3), (1, 8, 12.5), (0, 10, 0.0), (10, 10, 100.0), (1, 3, 33.3), (5, 0, None)],
)
def test_el_porcentaje_se_redondea_a_un_decimal_con_la_mitad_para_arriba(parte, total, esperado):
    assert tacto.porcentaje(parte, total) == esperado


def test_vaca_por_vaca():
    vacas = [
        Vaca(PRENADA, "cabeza", 3),
        Vaca(VACIA, None, 2.5),
        Vaca(PRENADA, "cola", None),
        Vaca(PRENADA, None, 3.5),  # preñada sin decir cabeza, cuerpo ni cola
    ]
    c = tacto.de_vacas(vacas)
    assert (c.prenadas, c.vacias, c.total, c.porcentaje) == (3, 1, 4, 75.0)
    assert c.estadios == {"cabeza": 1, "cola": 1}
    assert (c.cc, c.con_cc) == (3.0, 3)


def test_comparar_el_cierre_con_las_vacas_dictadas():
    cierre = tacto.de_cierre(prenadas=3, cabeza=2, cuerpo=1, vacias=1)
    vacas = tacto.de_vacas([Vaca(PRENADA, "cabeza"), Vaca(PRENADA, "cuerpo"), Vaca(VACIA)])
    assert tacto.comparar(cierre, vacas) == [("preñadas", 2, 3), ("cabeza", 1, 2), ("total", 3, 4)]
    assert tacto.comparar(vacas, vacas) == []
