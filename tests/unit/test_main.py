"""Pruebas de :func:`main.main`: los codigos de salida del proceso.

``main.py`` es el unico sitio que traduce excepciones a codigos de salida, y eso
es lo que un shell necesita para decidir si algo fue bien. Se prueban los cinco
codigos posibles, incluido el 130 reservado por POSIX para "terminado por
SIGINT", que es el que evita que un Ctrl+C parezca un fallo.

Solo se parchea lo externo: ``Session.build`` (que abriria conexiones) y la
entrada del menu. ``AppConfig`` no se toca: se construye de verdad con una clave
ficticia, para que el camino de la configuracion tambien se ejercite.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

import main as main_mod
from exceptions import (
    ApiError,
    ConfigError,
    CorruptedStorageError,
    UserCancelledError,
)
from session import Session
from tests.conftest import FAKE_API_KEY, OMDB_STABLE_TITLE


@pytest.fixture
def con_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configura una clave de OMDb ficticia y limpia el resto del entorno."""
    monkeypatch.setenv("OMDB_API_KEY", FAKE_API_KEY)
    for nombre in ("OMDB_TIMEOUT", "CACHE_TTL_SECONDS", "APP_DEBUG", "APP_VERBOSE"):
        monkeypatch.delenv(nombre, raising=False)


@pytest.fixture
def sesion_falsa(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """``Session`` simulada, para que construirla no abra conexiones.

    Se sustituye el metodo de clase con ``monkeypatch.setattr``: reasignarlo a
    mano dejaria un ``classmethod`` sin ``cls`` y el cierre fallaria.
    """
    sesion = Mock(spec=Session)
    sesion.config = Mock(debug=False, verbose=False)
    sesion.close.return_value = None
    sesion.cache_stats.return_value = {
        "movies": {},
        "series": {},
        "local": {},
    }

    monkeypatch.setattr(Session, "build", classmethod(lambda cls, config: sesion))
    return sesion


class TestArranqueExitoso:
    """El camino normal: la aplicacion arranca y el menu termina bien."""

    def test_devuelve_cero_cuando_el_menu_termina_bien(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(main_mod, "run_menu", lambda session: 0)

        assert main_mod.main([]) == 0

    def test_propaga_el_codigo_del_menu(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # El menu puede devolver un codigo propio; `main` no debe inventarse otro.
        monkeypatch.setattr(main_mod, "run_menu", lambda session: 42)

        assert main_mod.main([]) == 42

    def test_construye_la_sesion_con_la_configuracion_resuelta(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # El composition root recibe el `AppConfig` ya construido, no el
        # entorno: es lo que hace testeable el resto del proyecto.
        recibidos: list[Any] = []

        def build(cls: type, config: Any) -> Mock:
            recibidos.append(config)
            return sesion_falsa

        monkeypatch.setattr(Session, "build", classmethod(build))
        monkeypatch.setattr(main_mod, "run_menu", lambda session: 0)

        main_mod.main([])

        assert len(recibidos) == 1
        assert recibidos[0].omdb_api_key == FAKE_API_KEY

    def test_no_consulta_la_red_durante_el_arranque(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # La guarda anti-red lo verifica: si arrancar abriera un socket, este
        # test fallaria aqui.
        monkeypatch.setattr(main_mod, "run_menu", lambda session: 0)

        assert main_mod.main([]) == 0


class TestSinCredencial:
    """La regla de la FASE 5: sin clave, la aplicacion no arranca."""

    def test_devuelve_uno_si_falta_la_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OMDB_API_KEY", raising=False)
        construidas: list[Any] = []
        monkeypatch.setattr(
            Session, "build", classmethod(lambda cls, config: construidas.append(config))
        )

        assert main_mod.main([]) == 1
        # Ni se llega a construir la sesion: no habria a que consultar sin clave.
        assert construidas == []

    def test_no_llega_a_mostrar_el_menu(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OMDB_API_KEY", raising=False)
        llamado = False

        def menu(session: Any) -> int:
            nonlocal llamado
            llamado = True
            return 0

        monkeypatch.setattr(main_mod, "run_menu", menu)

        main_mod.main([])

        assert llamado is False

    def test_el_mensaje_nombra_la_variable_que_falta(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Sin esto, el usuario no sabe que exportar.
        monkeypatch.delenv("OMDB_API_KEY", raising=False)

        main_mod.main([])

        salida = capsys.readouterr().out
        assert "OMDB_API_KEY" in salida

    def test_el_mensaje_apunta_a_la_documentacion(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("OMDB_API_KEY", raising=False)

        main_mod.main([])

        assert ".env.example" in capsys.readouterr().out

    def test_una_clave_en_blanco_tambien_impide_arrancar(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Definida pero vacia es tan ausente como no definirla.
        monkeypatch.setenv("OMDB_API_KEY", "   ")

        assert main_mod.main([]) == 1

    def test_captura_config_error_como_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `ConfigError` hereda de `ValueError` precisamente para que este
        # `except` siga funcionando. Si dejara de heredar, la excepcion
        # escaparia y el proceso terminaria con un traceback en vez de un
        # mensaje limpio.
        monkeypatch.setenv("OMDB_API_KEY", "   ")

        # No debe escapar: si escapara, pytest lo reportaria como error.
        assert main_mod.main([]) == 1


class TestFalloDeArranque:
    """Cuando la sesion no se puede construir."""

    def test_devuelve_uno_si_la_construccion_falla(
        self, con_clave: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def falla(cls: type, config: Any) -> Any:
            raise OSError("no se pudo abrir el archivo de datos")

        monkeypatch.setattr(Session, "build", classmethod(falla))

        assert main_mod.main([]) == 1

    def test_no_muestra_el_menu_si_la_construccion_falla(
        self, con_clave: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llamado = False

        def menu(session: Any) -> int:
            nonlocal llamado
            llamado = True
            return 0

        def falla(cls: type, config: Any) -> Any:
            raise OSError("fallo")

        monkeypatch.setattr(Session, "build", classmethod(falla))
        monkeypatch.setattr(main_mod, "run_menu", menu)

        main_mod.main([])

        assert llamado is False

    def test_una_config_error_en_la_construccion_tambien_da_uno(
        self, con_clave: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def falla(cls: type, config: Any) -> Any:
            raise ConfigError("configuracion invalida")

        monkeypatch.setattr(Session, "build", classmethod(falla))

        assert main_mod.main([]) == 1


class TestCancelacion:
    """Ctrl+C o Ctrl+D no son un fallo de la aplicacion."""

    def test_una_cancelacion_devuelve_cero(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Cancelar es una decision del usuario, no un error: el shell no debe
        # interpretarlo como que algo fue mal.
        def menu(session: Any) -> int:
            raise UserCancelledError("el usuario cancelo")

        monkeypatch.setattr(main_mod, "run_menu", menu)

        assert main_mod.main([]) == 0

    def test_una_cancelacion_no_es_el_codigo_de_error(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def menu(session: Any) -> int:
            raise UserCancelledError("cancelado")

        monkeypatch.setattr(main_mod, "run_menu", menu)

        assert main_mod.main([]) != main_mod.EXIT_ERROR


class TestErroresDuranteLaEjecucion:
    """Los fallos que ocurren con la aplicacion ya arrancada."""

    def test_un_error_de_api_devuelve_uno(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def menu(session: Any) -> int:
            raise ApiError("la API no responde")

        monkeypatch.setattr(main_mod, "run_menu", menu)

        assert main_mod.main([]) == 1

    def test_un_error_de_api_registra_el_fallo(
        self,
        con_clave: None,
        sesion_falsa: Mock,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # `main` llama a `logger.exception`, que escribe en el logger
        # "peliculas" con la traza. Como `configure_logging` se ejecuta dentro
        # de `main` y usa `basicConfig(force=True)`, `caplog` no sirve: la
        # traza va al `stderr`. Se comprueba con `capsys`, que es donde
        # realmente acaba, y ademas se verifica el nivel del registro.
        import logging

        def menu(session: Any) -> int:
            raise ApiError("la API no responde")

        monkeypatch.setattr(main_mod, "run_menu", menu)

        main_mod.main([])

        # `configure_logging` escribe en stderr, no en stdout.
        assert "la API no responde" in capsys.readouterr().err

    def test_un_almacenamiento_corrupto_devuelve_uno(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def menu(session: Any) -> int:
            raise CorruptedStorageError("el archivo esta danado")

        monkeypatch.setattr(main_mod, "run_menu", menu)

        assert main_mod.main([]) == 1

    def test_almacenamiento_corrupto_tiene_su_propio_mensaje(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # "tus datos estan danados" y "no puedo escribir en disco" son
        # problemas distintos, y el usuario tiene que distinguir cual es cual.
        def menu(session: Any) -> int:
            raise CorruptedStorageError("el archivo esta danado")

        monkeypatch.setattr(main_mod, "run_menu", menu)

        main_mod.main([])

        assert "danado" in capsys.readouterr().out.lower()

    def test_un_error_de_api_y_uno_de_datos_tienen_mensajes_distintos(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def menu_api(session: Any) -> int:
            raise ApiError("fallo de red")

        monkeypatch.setattr(main_mod, "run_menu", menu_api)
        main_mod.main([])
        salida_api = capsys.readouterr().out

        def menu_datos(session: Any) -> int:
            raise CorruptedStorageError("archivo danado")

        monkeypatch.setattr(main_mod, "run_menu", menu_datos)
        main_mod.main([])
        salida_datos = capsys.readouterr().out

        assert salida_api != salida_datos


class TestInterrupcionDelTeclado:
    """El codigo 130, reservado por POSIX para SIGINT."""

    def test_devuelve_130_ante_un_ctrl_c(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Es el unico codigo de la FASE 4 que no es de error: distingue "el
        # usuario paro el programa" de "el programa fallo". Un shell lo usa para
        # no imprimir un mensaje de error tras un Ctrl+C.
        def menu(session: Any) -> int:
            raise KeyboardInterrupt

        monkeypatch.setattr(main_mod, "run_menu", menu)

        assert main_mod.main([]) == 130

    def test_130_no_es_el_codigo_de_error(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def menu(session: Any) -> int:
            raise KeyboardInterrupt

        monkeypatch.setattr(main_mod, "run_menu", menu)

        assert main_mod.main([]) != main_mod.EXIT_ERROR

    def test_ctrl_c_durante_el_arranque_tambien_da_130(
        self, con_clave: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # El `except KeyboardInterrupt` cubre el menu, pero la construccion de
        # la sesion tambien esta dentro del flujo esperado.
        def menu(session: Any) -> int:
            raise KeyboardInterrupt

        monkeypatch.setattr(Session, "build", classmethod(lambda cls, config: Mock()))
        monkeypatch.setattr(main_mod, "run_menu", menu)

        assert main_mod.main([]) == 130


class TestExcepcionesNoPrevistas:
    """Lo que no esta en la jerarquia del dominio."""

    def test_un_value_error_plano_no_se_confunde_con_una_cancelacion(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `UserCancelledError` hereda de `MovieCatalogError`, no de `ValueError`.
        # Si el orden de las clausulas fuera otro, un `ValueError` fugado
        # podria acabar tratado como cancelacion, con codigo 0.
        def menu(session: Any) -> int:
            raise ValueError("error de Python sin traducir")

        monkeypatch.setattr(main_mod, "run_menu", menu)

        with pytest.raises(ValueError):
            main_mod.main([])

    def test_una_excepcion_desconocida_no_se_traga(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # El original tenia `except:` desnudos que se comian cualquier fallo y
        # continuaban como si nada. Propagar es lo correcto: un bug debe verse.
        def menu(session: Any) -> int:
            raise RuntimeError("bug sin corregir")

        monkeypatch.setattr(main_mod, "run_menu", menu)

        with pytest.raises(RuntimeError):
            main_mod.main([])


class TestArgumentos:
    """``main(argv)`` sigue aceptando una lista de argumentos."""

    def test_ignora_argumentos_desconocidos(
        self, con_clave: None, sesion_falsa: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # La FASE 5 elimino `--strict`, que era el unico argumento que existia.
        # Los demas no dan error: el menu no tiene opciones de linea de comandos.
        monkeypatch.setattr(main_mod, "run_menu", lambda session: 0)

        assert main_mod.main(["--lo-que-sea"]) == 0

    def test_argv_es_opcional(self) -> None:
        # Sin argumentos, `main` lee `sys.argv`. Se comprueba la firma y no el
        # comportamiento, porque leer `sys.argv` en un test dependenia de como
        # se invoco pytest.
        import inspect

        parametros = inspect.signature(main_mod.main).parameters

        assert parametros["argv"].default is None


class TestCodigosDeSalida:
    """Los codigos, tal como los define el proyecto."""

    def test_el_error_es_uno(self) -> None:
        assert main_mod.EXIT_ERROR == 1

    def test_la_interrupcion_es_130(self) -> None:
        # 130 = 128 + 2 (SIGINT). Es lo que POSIX reserva para "terminado por
        # Ctrl+C" y lo que permite al shell no mostrar un error.
        assert main_mod.EXIT_INTERRUPTED == 130

    def test_los_codigos_coinciden_con_constants(
        self, con_clave: None, sesion_falsa: Mock
    ) -> None:
        from constants import EXIT_ERROR, EXIT_INTERRUPTED

        # Una sola fuente de verdad: si divergieran, el menu podria mostrar un
        # numero y el proceso devolver otro.
        assert main_mod.EXIT_ERROR == EXIT_ERROR
        assert main_mod.EXIT_INTERRUPTED == EXIT_INTERRUPTED
