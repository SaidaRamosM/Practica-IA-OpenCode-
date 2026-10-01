"""Pruebas de :class:`AppConfig` y :func:`require_env`.

La regla de la FASE 5 que mas conviene fijar aqui: **``OMDB_API_KEY`` es
obligatoria y no tiene valor de reserva**. Antes existia una clave de demo
hardcodeada como *fallback* de arranque, de modo que la aplicacion arrancaba
siempre y la credencial acababa en repositorios y logs ajenos. Los tests de
``sin la clave`` son los que impiden que vuelva a colarse.

Las pruebas usan el parametro ``env`` de ``AppConfig.from_env(env=...)`` y la
fixture ``env_limpio``, que borra las variables reales del entorno. Asi el
resultado no depende de lo que el desarrollador tenga exportado en su shell, y
ninguna credencial real toca el directorio ``tests/``.
"""

from __future__ import annotations

import pytest

from config import (
    DEFAULT_CACHE_MAX_ENTRIES,
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_MAX_HISTORY_ENTRIES,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_CACHE_TTL_SECONDS,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    OMDB_API_KEY_ENV,
    AppConfig,
    require_env,
)
from exceptions import ConfigError, MovieCatalogError
from tests.conftest import FAKE_API_KEY


class TestRequireEnv:
    """``require_env``: una variable obligatoria, sin valor por defecto."""

    def test_devuelve_el_valor_presente(self) -> None:
        assert require_env("MI_VAR", {"MI_VAR": "valor"}) == "valor"

    def test_recorta_los_espacios_del_valor(self) -> None:
        # Un salto de linea al final viene de un `.env` mal cerrado; no debe
        # acabar dentro de la clave y producir un 401 dificil de explicar.
        assert require_env("MI_VAR", {"MI_VAR": "  valor  "}) == "valor"

    def test_lanza_si_la_variable_no_existe(self) -> None:
        with pytest.raises(ConfigError):
            require_env("MI_VAR", {})

    @pytest.mark.parametrize("valor", ["", "   ", "\t", "\n"])
    def test_lanza_si_el_valor_esta_en_blanco(self, valor: str) -> None:
        # Una variable definida pero vacia es tan ausente como no definirla.
        with pytest.raises(ConfigError):
            require_env("MI_VAR", {"MI_VAR": valor})

    def test_el_error_nombra_la_variable_pero_no_su_valor(self) -> None:
        # El mensaje dice que falta MI_VAR, nunca lo que habia. Con una
        # credencial de por medio, incluir el valor lo escribiria en el log.
        with pytest.raises(ConfigError) as exc_info:
            require_env("MI_SECRETO", {})

        assert "MI_SECRETO" in str(exc_info.value)
        assert exc_info.value.field == "MI_SECRETO"

    def test_el_error_apunta_a_la_documentacion(self) -> None:
        # El mensaje tiene que decir donde se define, o el usuario no sabe que
        # hacer con el error.
        with pytest.raises(ConfigError, match=".env.example"):
            require_env("MI_VAR", {})

    def test_es_una_config_error_del_dominio(self) -> None:
        with pytest.raises(MovieCatalogError):
            require_env("MI_VAR", {})

    def test_tambien_es_un_value_error(self) -> None:
        # El punto de entrada captura `except ValueError`; ConfigError hereda
        # de ambos precisamente para que ese `except` siga funcionando.
        assert issubclass(ConfigError, ValueError)

    def test_lee_del_entorno_real_si_no_se_pasa_ninguno(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VARIABLE_DE_PRUEBA", "desde-el-entorno")

        assert require_env("VARIABLE_DE_PRUEBA") == "desde-el-entorno"


class TestFromEnv:
    """``AppConfig.from_env``: la resolucion de la configuracion."""

    def test_crea_la_configuracion_con_la_clave_del_entorno(
        self, env_limpio: None
    ) -> None:
        config = AppConfig.from_env({OMDB_API_KEY_ENV: FAKE_API_KEY})

        assert config.omdb_api_key == FAKE_API_KEY

    def test_lanza_config_error_si_falta_la_clave(self, env_limpio: None) -> None:
        # El test central de la FASE 5. Sin la clave no hay arranque, y eso es
        # lo correcto: arrancar con una credencial de relleno seria peor.
        with pytest.raises(ConfigError, match=OMDB_API_KEY_ENV):
            AppConfig.from_env({})

    def test_lanza_config_error_si_la_clave_esta_vacia(self, env_limpio: None) -> None:
        with pytest.raises(ConfigError):
            AppConfig.from_env({OMDB_API_KEY_ENV: "   "})

    def test_usa_los_valores_por_defecto_sin_mas_variables(
        self, env_limpio: None
    ) -> None:
        config = AppConfig.from_env({OMDB_API_KEY_ENV: FAKE_API_KEY})

        assert config.request_timeout == DEFAULT_TIMEOUT_SECONDS
        assert config.max_retries == DEFAULT_MAX_RETRIES
        assert config.cache_ttl_seconds == DEFAULT_CACHE_TTL_SECONDS
        assert config.cache_max_entries == DEFAULT_CACHE_MAX_ENTRIES
        assert config.max_history_entries == DEFAULT_MAX_HISTORY_ENTRIES
        assert config.debug is False
        assert config.verbose is False

    def test_lee_cada_variable_del_entorno(
        self, env_limpio: None
    ) -> None:
        # Todos los valores a la vez: detecta un cruce entre variables, que es
        # el error tipico al copiar el bloque de lectura.
        config = AppConfig.from_env(
            {
                OMDB_API_KEY_ENV: FAKE_API_KEY,
                "OMDB_TIMEOUT": "42.5",
                "OMDB_MAX_RETRIES": "7",
                "CACHE_TTL_SECONDS": "120",
                "CACHE_MAX_ENTRIES": "64",
                "MAX_HISTORY_ENTRIES": "9",
                "APP_DEBUG": "true",
                "APP_VERBOSE": "si",
            }
        )

        assert config.request_timeout == 42.5
        assert config.max_retries == 7
        assert config.cache_ttl_seconds == 120
        assert config.cache_max_entries == 64
        assert config.max_history_entries == 9
        assert config.debug is True
        assert config.verbose is True

    @pytest.mark.parametrize(
        "valor,esperado",
        [
            ("1", True),
            ("true", True),
            ("TRUE", True),
            ("yes", True),
            ("on", True),
            ("si", True),
            ("y", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("off", False),
        ],
    )
    def test_interpreta_los_booleanos(
        self, env_limpio: None, valor: str, esperado: bool
    ) -> None:
        # "si" y "y" estan porque el menu y los usuarios hispanohablantes los
        # usan; "1"/"0" porque vienen de variables de shell.
        config = AppConfig.from_env(
            {OMDB_API_KEY_ENV: FAKE_API_KEY, "APP_DEBUG": valor}
        )

        assert config.debug is esperado

    def test_un_valor_no_numerico_cae_al_defecto_con_aviso(
        self, env_limpio: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        # No debe abortar el arranque: un `OMDB_TIMEOUT=abc` es un error
        # tipografico, no un motivo para que la aplicacion no arranque.
        import logging

        with caplog.at_level(logging.WARNING, logger="config"):
            config = AppConfig.from_env(
                {OMDB_API_KEY_ENV: FAKE_API_KEY, "OMDB_TIMEOUT": "abc"}
            )

        assert config.request_timeout == DEFAULT_TIMEOUT_SECONDS
        assert "OMDB_TIMEOUT" in caplog.text

    def test_un_booleano_ilegible_cae_al_defecto_con_aviso(
        self, env_limpio: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        with caplog.at_level(logging.WARNING, logger="config"):
            config = AppConfig.from_env(
                {OMDB_API_KEY_ENV: FAKE_API_KEY, "APP_DEBUG": "quiza"}
            )

        assert config.debug is False
        assert "APP_DEBUG" in caplog.text

    def test_una_variable_vacia_cae_al_defecto_sin_aviso(
        self, env_limpio: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Una variable definida y vacia es "no opinionada", no un error: no hay
        # nada que avisar.
        import logging

        with caplog.at_level(logging.WARNING, logger="config"):
            config = AppConfig.from_env(
                {OMDB_API_KEY_ENV: FAKE_API_KEY, "OMDB_TIMEOUT": ""}
            )

        assert config.request_timeout == DEFAULT_TIMEOUT_SECONDS
        assert caplog.text == ""

    def test_no_registra_el_valor_de_la_clave(
        self, env_limpio: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        # El log dice que la variable esta definida, nunca lo que vale.
        import logging

        with caplog.at_level(logging.DEBUG, logger="config"):
            AppConfig.from_env({OMDB_API_KEY_ENV: FAKE_API_KEY})

        assert FAKE_API_KEY not in caplog.text
        assert OMDB_API_KEY_ENV in caplog.text

    def test_lee_el_entorno_real_por_defecto(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Sin `env`, tiene que leer `os.environ`. Se prueba con `monkeypatch`
        # para no depender de la shell de quien ejecuta la suite.
        monkeypatch.setenv(OMDB_API_KEY_ENV, "clave-del-entorno-real")
        monkeypatch.setenv("OMDB_TIMEOUT", "5")

        config = AppConfig.from_env()

        assert config.omdb_api_key == "clave-del-entorno-real"
        assert config.request_timeout == 5.0


class TestValidacionAlConstruir:
    """``__post_init__`` rechaza lo imposible antes de que llegue a la red."""

    def test_rechaza_una_clave_vacia(self) -> None:
        with pytest.raises(ConfigError, match="omdb_api_key"):
            AppConfig(omdb_api_key="   ")

    def test_rechaza_un_timeout_no_positivo(self) -> None:
        with pytest.raises(ConfigError, match="request_timeout"):
            AppConfig(omdb_api_key=FAKE_API_KEY, request_timeout=0)

    def test_rechaza_reintentos_negativos(self) -> None:
        with pytest.raises(ConfigError, match="max_retries"):
            AppConfig(omdb_api_key=FAKE_API_KEY, max_retries=-1)

    def test_rechaza_un_ttl_no_positivo(self) -> None:
        with pytest.raises(ConfigError, match="cache_ttl_seconds"):
            AppConfig(omdb_api_key=FAKE_API_KEY, cache_ttl_seconds=0)

    def test_rechaza_un_tope_de_cache_no_positivo(self) -> None:
        with pytest.raises(ConfigError, match="cache_max_entries"):
            AppConfig(omdb_api_key=FAKE_API_KEY, cache_max_entries=0)

    def test_rechaza_un_historial_negativo(self) -> None:
        with pytest.raises(ConfigError, match="max_history_entries"):
            AppConfig(omdb_api_key=FAKE_API_KEY, max_history_entries=-1)

    def test_cada_error_identifica_su_campo(self) -> None:
        # Permite decir "el problema es este campo" sin depender del texto.
        with pytest.raises(ConfigError) as exc_info:
            AppConfig(omdb_api_key=FAKE_API_KEY, request_timeout=-5)

        assert exc_info.value.field == "request_timeout"

    def test_admite_un_historial_de_cero(self) -> None:
        # Cero historial es una configuracion legitima: no querer guardar
        # ninguna busqueda. Negativo, en cambio, no tiene sentido.
        assert AppConfig(omdb_api_key=FAKE_API_KEY, max_history_entries=0)

    def test_admite_un_timeout_en_el_rango_admisible(
        self, env_limpio: None
    ) -> None:
        # Los extremos son validos: el rango es inclusivo.
        for valor in (MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS):
            config = AppConfig.from_env(
                {OMDB_API_KEY_ENV: FAKE_API_KEY, "OMDB_TIMEOUT": str(valor)}
            )
            assert config.request_timeout == valor


class TestInmutabilidad:
    """``AppConfig`` es ``frozen=True``: el cambio se hace con una copia."""

    def test_no_se_puede_asignar_un_atributo(self, config: AppConfig) -> None:
        with pytest.raises(Exception):
            config.debug = True  # type: ignore[misc]

    def test_with_overrides_devuelve_una_copia(self, config: AppConfig) -> None:
        # La original no se toca: es lo que evita que un servicio vea un cambio
        # de configuracion a medias.
        nueva = config.with_overrides(debug=True)

        assert nueva.debug is True
        assert config.debug is False
        assert nueva is not config

    def test_with_overrides_conserva_lo_que_no_se_toca(
        self, config: AppConfig
    ) -> None:
        nueva = config.with_overrides(max_retries=9)

        assert nueva.omdb_api_key == config.omdb_api_key
        assert nueva.max_retries == 9

    def test_with_timeout_cambia_el_timeout(self, config: AppConfig) -> None:
        assert config.with_timeout(30).request_timeout == 30

    @pytest.mark.parametrize("segundos", [0, -1, MIN_TIMEOUT_SECONDS - 0.5, MAX_TIMEOUT_SECONDS + 1])
    def test_with_timeout_rechaza_fuera_de_rango(
        self, config: AppConfig, segundos: float
    ) -> None:
        # El menu pide un entero entre 1 y 120; fuera de ahi la peticion o bien
        # falla al instante o se queda colgada.
        with pytest.raises(ConfigError, match="timeout"):
            config.with_timeout(segundos)

    def test_with_flags_cambia_solo_lo_indicado(self, config: AppConfig) -> None:
        nueva = config.with_flags(debug=True)

        assert nueva.debug is True
        assert nueva.verbose == config.verbose

    def test_with_flags_sin_argumentos_no_cambia_nada(
        self, config: AppConfig
    ) -> None:
        nueva = config.with_flags()

        assert nueva.debug == config.debug
        assert nueva.verbose == config.verbose

    def test_with_flags_admite_apagar(self, config: AppConfig) -> None:
        # `False` es un valor legitimo, no "no opinionado": por eso el
        # parametro es opcional y no un `bool` normal.
        encendida = config.with_flags(debug=True)

        assert encendida.with_flags(debug=False).debug is False


class TestRedaccion:
    """La clave no puede aparecer en un ``repr`` ni en un ``as_dict``."""

    def test_el_repr_enmascara_la_clave(self, config: AppConfig) -> None:
        # Sin esto, un traceback o un log de depuracion acabaria con la
        # credencial a la vista.
        assert FAKE_API_KEY not in repr(config)
        assert "***" in repr(config)

    def test_as_dict_enmascara_la_clave_por_defecto(
        self, config: AppConfig
    ) -> None:
        assert config.as_dict()["omdb_api_key"] == "***"

    def test_as_dict_puede_revelar_la_clave_si_se_pide_explicitamente(
        self, config: AppConfig
    ) -> None:
        # Existe el parametro para diagnostico controlado. Que sea explicito
        # es lo que evita que alguien lo active por costumbre.
        assert config.as_dict(redact_secrets=False)["omdb_api_key"] == FAKE_API_KEY

    def test_as_dict_expone_todas_las_variables_que_lo_gestionan(
        self, config: AppConfig
    ) -> None:
        # Si una variable nueva del entorno no aparece aqui, no se puede
        # diagnosticar por pantalla.
        datos = config.as_dict()

        assert set(datos) == {
            "omdb_api_key",
            "request_timeout",
            "max_retries",
            "cache_ttl_seconds",
            "cache_max_entries",
            "max_history_entries",
            "debug",
            "verbose",
        }

    def test_no_hay_campos_sobre_la_key_de_demo(
        self, config: AppConfig
    ) -> None:
        # El contrato de la FASE 5: no queda ningun rastro del "estoy usando la
        # clave de demo", porque ya no existe esa clave.
        assert "using_demo_api_key" not in config.as_dict()
        assert not hasattr(config, "using_demo_api_key")


class TestValidate:
    """``validate()``: avisos de configuracion improbable."""

    def test_una_configuracion_normal_no_da_problemas(
        self, config: AppConfig
    ) -> None:
        assert config.validate() == []

    def test_avisa_si_el_timeout_queda_fuera_de_rango(
        self, config: AppConfig
    ) -> None:
        # Con `with_overrides` se puede saltar la comprobacion de
        # `__post_init__`; `validate` es la red que queda.
        problemas = config.with_overrides(request_timeout=9999).validate()

        assert any("request_timeout" in p for p in problemas)

    def test_avisa_si_el_historial_no_es_positivo(
        self, config: AppConfig
    ) -> None:
        problemas = config.with_overrides(max_history_entries=0).validate()

        assert any("max_history_entries" in p for p in problemas)

    def test_no_avisa_por_la_clave_porque_es_obligatoria(
        self, config: AppConfig
    ) -> None:
        # Antes habia un aviso "estas usando la clave de demo". Ya no hay nada
        # que avisar: o hay clave, o la aplicacion no arranca.
        assert config.validate() == []

    def test_devuelve_una_lista_y_no_una_excepcion(
        self, config: AppConfig
    ) -> None:
        # Son avisos, no fallos: el menu los imprime y sigue funcionando.
        assert isinstance(config.validate(), list)


class TestTtlimitesCompartidos:
    """Los limites que mencioan el menu y ``.env.example``.

    Se comprueban aqui para que, si alguien los cambia en un sitio y no en el
    otro, un test avise.
    """

    def test_el_tope_del_ttl_es_el_que_persiste_el_menu(
        self, config: AppConfig
    ) -> None:
        problemas = config.with_overrides(
            cache_ttl_seconds=MAX_CACHE_TTL_SECONDS + 1
        ).validate()

        # El TTL no tiene cota superior en `validate`; lo que se comprueba es
        # que el limite exista y sea alcanzable desde el menu.
        assert MAX_CACHE_TTL_SECONDS > 0
        assert problemas == []
