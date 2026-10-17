"""El bot solo registra, consulta datos propios y muestra precios oficiales."""

from datetime import date

import pytest
from sqlalchemy import select

from app.fuentes import oficiales
from app.fuentes import precios as fuentes_precios
from app.fuentes import senasa as fuentes_senasa
from app.ia import interprete
from app.ia.proveedor import ErrorIA, IASaturada
from app.infra.config import config
from app.infra.modelos import Cotizacion
from app.modulos.comun import conversacion, precios, senasa
from app.nucleo import acceso, pipeline
from tests.ayudas import con_perfil

HOY = date(2026, 10, 9)
URL_PIZARRA = "https://www.cac.bcr.com.ar/es/precios-de-pizarra"
FUENTE = "Cámara Arbitral de Cereales - Bolsa de Comercio de Rosario"


@pytest.fixture
def respuestas(monkeypatch):
    datos: dict[str, object] = {}
    monkeypatch.setattr(interprete, "interpretar", lambda texto, hoy, historial=None, partes=(): datos[texto])
    return datos


def _usuario(db, telefono="5491100000001"):
    return con_perfil(db, telefono)


@pytest.mark.parametrize(
    "salida",
    [
        {"intencion": "fuera_de_alcance"},
        # Aunque el modelo devuelva texto propio, nunca se muestra.
        {"intencion": "charla", "respuesta": "Te recomiendo vender ya"},
        {"intencion": "registrar", "eventos": "no es una lista"},
        {"intencion": "consultar"},
        {"intencion": "inventada"},
        ["no", "es", "un", "objeto"],
    ],
)
def test_todo_lo_que_no_es_valido_es_fuera_de_alcance(db, respuestas, salida):
    u = _usuario(db)
    respuestas["x"] = salida
    r = pipeline.manejar_mensaje(db, u.telefono, "x", hoy=HOY)
    assert r == pipeline.FUERA_DE_ALCANCE
    assert "recomiendo" not in r


def test_mensaje_largo_no_llega_a_la_ia(db, respuestas):
    u = _usuario(db)
    r = pipeline.manejar_mensaje(db, u.telefono, "a" * (config.max_largo_mensaje + 1), hoy=HOY)
    assert "muy largo" in r  # si hubiera llamado a la IA, respuestas[...] tiraría KeyError


def test_limite_diario(db, respuestas, monkeypatch):
    monkeypatch.setattr(config, "limite_diario_ia", 2)
    u = _usuario(db)
    respuestas["x"] = {"intencion": "fuera_de_alcance"}
    assert pipeline.manejar_mensaje(db, u.telefono, "x", hoy=HOY) == pipeline.FUERA_DE_ALCANCE
    assert pipeline.manejar_mensaje(db, u.telefono, "x", hoy=HOY) == pipeline.FUERA_DE_ALCANCE
    assert "límite" in pipeline.manejar_mensaje(db, u.telefono, "x", hoy=HOY)
    # al otro día se renueva
    assert pipeline.manejar_mensaje(db, u.telefono, "x", hoy=date(2026, 10, 10)) == pipeline.FUERA_DE_ALCANCE
    # los comandos no gastan cupo
    assert "CAMPOBOT" in pipeline.manejar_mensaje(db, u.telefono, "ayuda", hoy=HOY)


def test_si_la_ia_esta_saturada_o_falla_el_mensaje_no_gasta_cupo(db, monkeypatch):
    monkeypatch.setattr(config, "limite_diario_ia", 2)
    u = _usuario(db)
    errores = {"saturada": IASaturada("OpenRouter 429"), "falla": ErrorIA("OpenRouter 400")}

    def interpretar(texto, hoy, historial=None, partes=()):
        if texto in errores:
            raise errores[texto]
        return {"intencion": "fuera_de_alcance"}

    monkeypatch.setattr(interprete, "interpretar", interpretar)
    for _ in range(3):
        assert pipeline.manejar_mensaje(db, u.telefono, "saturada", hoy=HOY) == pipeline.DEMANDA
        assert pipeline.manejar_mensaje(db, u.telefono, "falla", hoy=HOY) == pipeline.ERROR_IA
    assert pipeline.manejar_mensaje(db, u.telefono, "x", hoy=HOY) == pipeline.FUERA_DE_ALCANCE
    assert pipeline.manejar_mensaje(db, u.telefono, "x", hoy=HOY) == pipeline.FUERA_DE_ALCANCE
    assert "límite" in pipeline.manejar_mensaje(db, u.telefono, "x", hoy=HOY)


def test_usuario_sin_campo_no_usa_la_ia(db, respuestas):
    r = pipeline.manejar_mensaje(db, "5491100000009", "¿a cuánto está la soja?", hoy=HOY)
    assert r == acceso.NO_AUTORIZADO
    assert not acceso.puede_usar_ia(db, "5491100000009")


def _cargar_soja(db, fecha=date(2026, 10, 8), valor=310000, **extra):
    fuentes_precios.guardar(
        db,
        FUENTE,
        URL_PIZARRA,
        "granos",
        [
            {"producto": "Soja", "plaza": "Rosario", "valor": valor, "unidad": "t", "fecha": fecha, **extra},
        ],
    )


def test_precio_con_fuente_y_fecha(db, respuestas):
    u = _usuario(db)
    _cargar_soja(db, date(2026, 10, 7), 300000)
    _cargar_soja(db, date(2026, 10, 8), 310000)
    respuestas["¿a cuánto está la soja?"] = {"intencion": "precio", "precio": {"rubro": "granos", "producto": "soja"}}

    r = pipeline.manejar_mensaje(db, u.telefono, "¿a cuánto está la soja?", hoy=HOY)
    assert "🫘 *Soja* · Rosario\n      *$ 310.000* por t (ARS)" in r
    assert "Publicado el 08/10/2026" in r
    assert "La fuente no informa si incluye impuestos u otros costos." in r
    assert "300.000" not in r  # solo el último
    assert f"Fuente: {FUENTE}" in r and URL_PIZARRA in r
    assert "No son una recomendación" in r
    assert "puede no estar actualizado" not in r


def test_precio_viejo_avisa(db):
    _cargar_soja(db, date(2026, 9, 1))
    assert "Dato de hace 38 días, puede no estar actualizado" in precios.responder(db, "soja", None, HOY)


def test_precio_aclara_costos_adicionales(db):
    _cargar_soja(db, incluye_impuestos="no", costos_adicionales="Precio orientativo, sin gastos comerciales")
    r = precios.responder(db, "soja", None, HOY)
    assert "No incluye impuestos (IVA). Precio orientativo, sin gastos comerciales." in r


def test_moneda_desconocida_se_rechaza(db):
    with pytest.raises(ValueError):
        _cargar_soja(db, moneda="EUR")


def test_sin_precio_no_inventa(db, respuestas):
    u = _usuario(db)
    respuestas["precio del novillo"] = {"intencion": "precio", "precio": {"rubro": "hacienda", "producto": "novillos"}}
    r = pipeline.manejar_mensaje(db, u.telefono, "precio del novillo", hoy=HOY)
    assert "No tengo precios cargados de ese producto" in r


def test_solo_acepta_fuentes_oficiales(db):
    for url in ("https://www.preciosdelcampo.com/soja", "http://www.bcr.com.ar/x", "https://bcr.com.ar.trucho.com/x"):
        with pytest.raises(ValueError):
            fuentes_precios.guardar(
                db, "Otra", url, "granos", [{"producto": "soja", "valor": 1, "unidad": "t", "fecha": HOY}]
            )
    assert oficiales.es_oficial("https://www.magyp.gob.ar/precios")
    assert oficiales.es_oficial(URL_PIZARRA)
    assert db.scalar(select(Cotizacion)) is None


def test_guardar_precio_dos_veces_no_duplica(db):
    _cargar_soja(db, valor=300000)
    _cargar_soja(db, valor=310000)
    filas = db.scalars(select(Cotizacion)).all()
    assert len(filas) == 1 and filas[0].valor == 310000 and filas[0].producto == "soja"


URL_SENASA = "https://www.argentina.gob.ar/senasa/registro-productos-veterinarios"


def _cargar_senasa(db):
    fuentes_senasa.reemplazar_registro(
        db,
        [
            {
                "nombre": "Ivomec 1%",
                "registro": "12.345",
                "titular": "Lab Uno SA",
                "principio_activo": "Ivermectina",
                "estado": "Vigente",
            },
            {
                "nombre": "Bioaftógen",
                "registro": "98.765",
                "titular": "Lab Dos SA",
                "principio_activo": "Virus aftosa inactivado",
                "estado": "Vigente",
            },
        ],
        date(2026, 10, 1),
        URL_SENASA,
    )


def test_senasa_por_principio_activo(db, respuestas):
    u = _usuario(db)
    _cargar_senasa(db)
    respuestas["¿la ivermectina está aprobada?"] = {
        "intencion": "producto_veterinario",
        "producto_veterinario": {"nombre": "IVERMECTINA"},
    }
    r = pipeline.manejar_mensaje(db, u.telefono, "¿la ivermectina está aprobada?", hoy=HOY)
    assert "*Ivomec 1%*" in r and "N° de registro: *12.345*" in r and "🏭 Lab Uno SA" in r
    assert "✅ Estado: vigente" in r
    assert "datos al 01/10/2026" in r and URL_SENASA in r
    assert "$" not in r  # nunca precios


def test_senasa_sin_tildes_y_sin_resultados(db):
    _cargar_senasa(db)
    assert "Bioaftógen" in senasa.responder(db, "bioaftogen")
    r = senasa.responder(db, "productoinexistente")
    assert "No encontré ese producto" in r and "no confirma que no esté registrado" in r


def test_senasa_solo_acepta_gob_ar(db):
    with pytest.raises(ValueError):
        fuentes_senasa.reemplazar_registro(db, [{"nombre": "x", "registro": "1"}], HOY, URL_PIZARRA)
    with pytest.raises(ValueError):  # un archivo vacío no borra el registro
        fuentes_senasa.reemplazar_registro(db, [], HOY, URL_SENASA)


def test_precio_sin_producto_repregunta(db, respuestas):
    u = _usuario(db)
    respuestas["precio"] = {"intencion": "precio", "precio": {}}
    assert (
        pipeline.manejar_mensaje(db, u.telefono, "precio", hoy=HOY)
        == "🤔 " + conversacion.PREGUNTAS["que_producto_precio"]
    )


def test_saludo_y_gracias(db, respuestas):
    u = _usuario(db)
    respuestas["buen día"] = {"intencion": "saludo"}
    respuestas["gracias!"] = {"intencion": "saludo", "agradece": True}
    assert pipeline.manejar_mensaje(db, u.telefono, "buen día", hoy=HOY) == conversacion.SALUDO
    assert pipeline.manejar_mensaje(db, u.telefono, "gracias!", hoy=HOY) == conversacion.GRACIAS


def test_aclarar_usa_solo_preguntas_fijas(db, respuestas):
    u = _usuario(db)
    respuestas["anotá"] = {"intencion": "aclarar", "falta": ["que_paso", "texto libre inventado", "que_paso"]}
    assert pipeline.manejar_mensaje(db, u.telefono, "anotá", hoy=HOY) == "🤔 " + conversacion.PREGUNTAS["que_paso"]
    respuestas["corregí eso"] = {"intencion": "aclarar", "falta": ["cual_registro", "que_cambiar"]}
    r = pipeline.manejar_mensaje(db, u.telefono, "corregí eso", hoy=HOY)
    assert r == "🤔 " + conversacion.PREGUNTAS["cual_registro"] + "\n" + conversacion.PREGUNTAS["que_cambiar"]


def _maiz(db):
    fuentes_precios.guardar(
        db,
        FUENTE,
        URL_PIZARRA,
        "granos",
        [{"producto": "Maíz", "plaza": "Rosario", "valor": 250000, "unidad": "t", "fecha": date(2026, 10, 8)}],
    )


def test_varios_precios_en_un_mensaje_agrupados_por_fuente(db, respuestas):
    u = _usuario(db)
    _cargar_soja(db)
    _maiz(db)
    respuestas["¿cuánto está la soja y el maíz?"] = {
        "acciones": [
            {"intencion": "precio", "precio": {"rubro": "granos", "producto": "soja"}},
            {"intencion": "precio", "precio": {"rubro": "granos", "producto": "maiz"}},
        ]
    }
    r = pipeline.manejar_mensaje(db, u.telefono, "¿cuánto está la soja y el maíz?", hoy=HOY)
    assert "*Soja* · Rosario" in r and "*Maíz* · Rosario" in r
    assert r.count("Fuente:") == 1 and r.count("No son una recomendación") == 1


def test_precio_que_falta_se_aclara_sin_perder_el_resto(db, respuestas):
    u = _usuario(db)
    _cargar_soja(db)
    respuestas["soja y girasol"] = {
        "acciones": [
            {"intencion": "precio", "precio": {"producto": "soja"}},
            {"intencion": "precio", "precio": {"producto": "girasol"}},
        ]
    }
    r = pipeline.manejar_mensaje(db, u.telefono, "soja y girasol", hoy=HOY)
    assert "*Soja* · Rosario" in r and "No tengo precios oficiales cargados de: Girasol." in r


def test_mezcla_de_pedidos_se_responde_en_orden(db, respuestas):
    u = _usuario(db)
    _cargar_soja(db)
    texto = "hola, anotá que llovieron 20 mm, ¿cuánto está la soja? y ¿me conviene vender?"
    respuestas[texto] = {
        "acciones": [
            {"intencion": "saludo"},
            {
                "intencion": "registrar",
                "eventos": [{"categoria": "campo", "tipo": "lluvia", "valor": 20, "unidad": "mm"}],
            },
            {"intencion": "precio", "precio": {"producto": "soja"}},
            {"intencion": "fuera_de_alcance"},
        ]
    }
    r = pipeline.manejar_mensaje(db, u.telefono, texto, hoy=HOY)
    assert r.index("ANOTADO") < r.index("*Soja* · Rosario") < r.index(pipeline.FUERA_PARCIAL)
    assert conversacion.SALUDO not in r and pipeline.FUERA_DE_ALCANCE not in r


def test_solo_fuera_de_alcance_o_solo_saludo(db, respuestas):
    u = _usuario(db)
    respuestas["a"] = {"acciones": [{"intencion": "fuera_de_alcance"}, {"intencion": "fuera_de_alcance"}]}
    respuestas["b"] = {"acciones": [{"intencion": "saludo"}, {"intencion": "saludo"}]}
    respuestas["c"] = {"acciones": []}
    assert pipeline.manejar_mensaje(db, u.telefono, "a", hoy=HOY) == pipeline.FUERA_DE_ALCANCE
    assert pipeline.manejar_mensaje(db, u.telefono, "b", hoy=HOY) == conversacion.SALUDO
    assert pipeline.manejar_mensaje(db, u.telefono, "c", hoy=HOY) == pipeline.FUERA_DE_ALCANCE


def test_tope_de_acciones_por_mensaje(db, respuestas):
    u = _usuario(db)
    respuestas["muchas"] = {
        "acciones": [
            {
                "intencion": "registrar",
                "eventos": [{"categoria": "campo", "tipo": "lluvia", "valor": i, "unidad": "mm"}],
            }
            for i in range(1, 20)
        ]
    }
    pipeline.manejar_mensaje(db, u.telefono, "muchas", hoy=HOY)
    from app.infra.modelos import Evento

    assert len(db.scalars(select(Evento)).all()) == pipeline.MAX_ACCIONES
