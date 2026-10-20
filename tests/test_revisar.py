"""Revisar las pruebas del modo prueba y sumarlas al set (paso 9b del plan)."""

import json
import shutil
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import terminal
from app.ia import evaluacion, revisar
from app.infra import migrar
from app.infra.db import crear_motor, motor_solo_lectura
from app.infra.modelos import Prueba
from app.nucleo import acciones
from tests.ayudas import con_perfil

HOY = date(2026, 10, 20)
LLUVIA = {"intencion": "registrar", "eventos": [{"categoria": "campo", "tipo": "lluvia", "valor": 5}]}
PENDIENTE = {
    "intencion": "anotar_pendiente",
    "pendiente": {"texto": "revisar las aguadas", "vence": {"dia_semana": "jueves"}},
}


def _prueba(db, texto: str, interpretacion: object, historial=(), pregunta=None) -> Prueba:
    usuario = con_perfil(db, "5492494000001")
    prueba = Prueba(
        usuario_id=usuario.id,
        texto=texto,
        audio=False,
        historial=[list(par) for par in historial],
        pregunta=pregunta,
        hoy=HOY,
        interpretacion=interpretacion,
        respuesta="🌧️ *LLUVIA ANOTADA*\n\n5 mm",
    )
    db.add(prueba)
    db.flush()
    return prueba


@pytest.fixture
def set_chico(tmp_path):
    """Una copia del set, para no tocar el de verdad."""
    ruta = tmp_path / "set.json"
    shutil.copy(evaluacion.SET, ruta)
    return ruta


def test_las_que_ya_estan_en_el_set_o_descartadas_no_se_muestran(db):
    nueva = _prueba(db, "llovieron 5 mm", LLUVIA)
    en_el_set = _prueba(db, "quiero ver mis campos", {"intencion": "mis_campos"})
    con_otra_charla = _prueba(db, "quiero ver mis campos", {"intencion": "mis_campos"}, [("usuario", "hola")])
    descartada = _prueba(db, "asdf", {"intencion": "aclarar"})
    pendientes = revisar.para_revisar(db, evaluacion.cargar(), {revisar.huella(descartada)})
    assert pendientes == [nueva, con_otra_charla]
    assert en_el_set not in pendientes


def test_aprobar_suma_la_frase_al_set_con_su_charla_pregunta_y_fechas(db, set_chico, tmp_path):
    prueba = _prueba(
        db, "che anotá que tengo que revisar las aguadas el jueves", PENDIENTE, [("usuario", "hola")], "borrar"
    )
    respuestas = iter(["x", "a", ""])  # una opción que no existe vuelve a preguntar; la función, la de por defecto
    salida: list[str] = []
    aprobadas, descartadas = revisar.revisar(
        [prueba],
        acciones.fechas,
        lambda _n: True,
        leer=lambda _p: next(respuestas),
        escribir=salida.append,
        ruta_set=set_chico,
        ruta_descartadas=tmp_path / "descartadas.txt",
    )
    assert (aprobadas, descartadas) == (1, 0)
    assert "Fechas calculadas: 2026-10-22" in salida[0] and "Pregunta abierta: borrar" in salida[0]
    ultima = evaluacion.cargar(set_chico)[-1]
    assert ultima == evaluacion.Frase(
        "anotar_pendiente",
        "che anotá que tengo que revisar las aguadas el jueves",
        ("anotar_pendiente",),
        (("usuario", "hola"),),
        "borrar",
        HOY,
        ("2026-10-22",),
    )
    assert json.loads(set_chico.read_text(encoding="utf-8"))["frases"][-1]["origen"] == "modo prueba"
    # Una por línea, como las demás.
    assert set_chico.read_text(encoding="utf-8").endswith('"origen": "modo prueba"}\n  ]\n}\n')


def test_corregir_descartar_saltar_y_salir(db, set_chico, tmp_path):
    corregida = _prueba(db, "borrá el campo de lomu", {"intencion": "borrar"})
    descartada = _prueba(db, "asdf", {"intencion": "aclarar"})
    saltada = _prueba(db, "llovieron 5 mm", LLUVIA)
    sin_ver = _prueba(db, "llovieron 6 mm", LLUVIA)
    respuestas = iter(["c", "borrar_kampo", "borrar_campo", "", "", "d", "s", "q"])
    salida: list[str] = []
    descartes = tmp_path / "descartadas.txt"
    aprobadas, descartadas = revisar.revisar(
        [corregida, descartada, saltada, sin_ver],
        acciones.fechas,
        {"borrar_campo", "borrar"}.__contains__,
        leer=lambda _p: next(respuestas),
        escribir=salida.append,
        ruta_set=set_chico,
        ruta_descartadas=descartes,
    )
    assert (aprobadas, descartadas) == (1, 1)
    assert "No conozco: borrar_kampo" in salida
    ultima = evaluacion.cargar(set_chico)[-1]
    assert (ultima.funcion, ultima.frase, ultima.intenciones, ultima.fechas) == (
        "borrar_campo",
        "borrá el campo de lomu",
        ("borrar_campo",),
        None,
    )
    assert revisar.descartadas(descartes) == {revisar.huella(descartada)}
    assert "asdf" not in descartes.read_text(encoding="utf-8")  # solo la huella


def test_la_base_se_lee_en_solo_lectura(tmp_path):
    url = f"sqlite:///{tmp_path / 'campo.db'}"
    motor = crear_motor(url)
    migrar.preparar_base(motor)
    motor.dispose()
    solo_lectura = motor_solo_lectura(url)
    with Session(solo_lectura) as db:
        assert db.scalars(select(Prueba)).all() == []
        with pytest.raises(OperationalError, match="readonly"):
            db.execute(text("delete from pruebas"))
    solo_lectura.dispose()


def test_eval_revisar_desde_la_terminal(tmp_path, set_chico, monkeypatch, capsys):
    """Con `--base`, lee esa base (en solo lectura) y suma lo aprobado al set."""
    url = f"sqlite:///{tmp_path / 'railway.db'}"
    motor = crear_motor(url)
    migrar.preparar_base(motor)
    with Session(motor) as db:
        _prueba(db, "llovieron 5 mm", LLUVIA)
        db.commit()
    motor.dispose()
    monkeypatch.setattr(evaluacion, "cargar", lambda: [])
    monkeypatch.setattr(revisar, "descartadas", lambda: set())
    agregadas: list[dict] = []
    monkeypatch.setattr(revisar, "agregar_al_set", lambda nueva, _ruta: agregadas.append(nueva))
    respuestas = iter(["a", "anotar_lluvia"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(respuestas))
    terminal.main(["eval", "revisar", "--base", url])
    assert [(a["funcion"], a["frase"], a["intenciones"]) for a in agregadas] == [
        ("anotar_lluvia", "llovieron 5 mm", ["registrar"])
    ]
    assert "Aprobadas: 1 · descartadas: 0." in capsys.readouterr().out
