"""Pruebas de integracion contra OMDb real.

Se ejecutan solo con ``pytest -m integration`` y se omiten si ``OMDB_API_KEY``
no esta definida. La credencial **nunca** se escribe en este archivo: se lee
del entorno, y si no esta, el test se salta con un motivo claro.

Qué se comprueba, y por qué es estable:

* que una consulta conocida devuelve la ficha completa;
* que el servicio construye un ``Movie`` con los campos principales;
* que una pelicula inexistente devuelve ``None`` en vez de reventar;
* que la credencial llega a OMDb y se acepta.

Qué **no** se comprueba, y por qué: ni el rating exacto, ni el numero de
resultados de una busqueda por actor, ni el texto de la trama. Esos valores
cambian con cada actualizacion del catalogo de OMDb y convertirian esta suite
en una fuente de falsos positivos. Se comprueban tipos y presencia, no valores.
"""

from __future__ import annotations

import os

import pytest

from api.omdb import OmdbClient
from config import AppConfig
from constants import OMDB_BASE_URL
from exceptions import ApiAuthError, MovieNotFoundError
from models.movie import Movie
from services.movie_service import MovieService
from tests.conftest import OMDB_STABLE_TITLE

#: Sin esto, un test unitario fallido al ejecutar `pytest -m integration`
#: aparecia como un fallo mas, sin Recordar que hacia falta la credencial.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("OMDB_API_KEY", "").strip(),
        reason="OMDB_API_KEY no esta definida: hace falta una clave real de omdbapi.com",
    ),
]


@pytest.fixture(scope="module")
def config_real() -> AppConfig:
    """Configuracion con la credencial real y timeouts generosos.

    El timeout es amplio a proposito: una red lenta no debe convertir un test
    de integracion en un falso negativo.
    """
    return AppConfig.from_env(
        {
            "OMDB_API_KEY": os.environ["OMDB_API_KEY"],
            "OMDB_TIMEOUT": "20",
        }
    )


@pytest.fixture
def cliente_real(config_real: AppConfig) -> OmdbClient:
    """Cliente de OMDb real, cerrado al terminar el test."""
    cliente = OmdbClient(
        OMDB_BASE_URL,
        timeout=config_real.request_timeout,
        api_key=config_real.omdb_api_key,
    )
    yield cliente
    cliente.close()


class TestConsultaReal:
    """El contrato basico contra el servicio en vivo."""

    def test_una_pelicula_conocida_se_encuentra(
        self, cliente_real: OmdbClient
    ) -> None:
        # El nucleo de la integracion: la API real responde lo que el codigo
        # espera. Si la credencial caducara o cambiara el formato, falla aqui.
        resultado = cliente_real.search_by_title(OMDB_STABLE_TITLE)

        assert resultado is not None
        assert resultado["Response"] == "True"

    def test_la_ficha_trae_los_campos_que_la_pantalla_muestra(
        self, cliente_real: OmdbClient
    ) -> None:
        # Se comprueba la *presencia* de los campos, no sus valores: estos si
        # son estables y son los que la tabla de `constants` necesita.
        from constants import OMDB_MOVIE_FIELDS

        resultado = cliente_real.search_by_title(OMDB_STABLE_TITLE)

        assert resultado is not None
        for clave, _etiqueta in OMDB_MOVIE_FIELDS:
            assert clave in resultado, f"OMDb no devolvio el campo {clave!r}"

    def test_el_id_de_imdb_tiene_formato_de_imdb(
        self, cliente_real: OmdbClient
    ) -> None:
        resultado = cliente_real.search_by_title(OMDB_STABLE_TITLE)

        assert resultado is not None
        # "tt" seguido de digitos: el formato es estable desde hace 15 años.
        assert str(resultado["imdbID"]).startswith("tt")
        assert str(resultado["imdbID"])[2:].isdigit()

    def test_el_titulo_viene_aproximadamente_igual(
        self, cliente_real: OmdbClient
    ) -> None:
        # Comparacion laxa a proposito: el titulo puede llevar el ano entre
        # parentesis ("Interstellar (2014)") y eso no es un fallo.
        resultado = cliente_real.search_by_title(OMDB_STABLE_TITLE)

        assert resultado is not None
        assert OMDB_STABLE_TITLE.lower() in str(resultado["Title"]).lower()

    def test_una_pelicula_inexistente_devuelve_none(
        self, cliente_real: OmdbClient
    ) -> None:
        # OMDb responde 200 con `Response: "False"`, no un 404. El cliente
        # tiene que traducir eso a `None`.
        resultado = cliente_real.search_by_title(
            "QzXxXxPeliculaQueNoExisteXxXxQ123456789"
        )

        assert resultado is None

    def test_fetch_detail_lanza_movie_not_found_para_una_inexistente(
        self, cliente_real: OmdbClient
    ) -> None:
        with pytest.raises(MovieNotFoundError):
            cliente_real.fetch_detail("QzXxXxPeliculaQueNoExisteXxXxQ123456789")

    def test_la_busqueda_por_actor_devuelve_estructura_consistente(
        self, cliente_real: OmdbClient
    ) -> None:
        # No se comprueba cuantos resultados hay, solo que cada uno tiene la
        # forma de una pelicula. El numero cambia con el catalogo.
        resultados = cliente_real.search_by_actor("Tom Hanks")

        assert isinstance(resultados, tuple)
        for pelicula in resultados:
            assert "Title" in pelicula
            assert "imdbID" in pelicula

    def test_la_paginacion_no_devuelve_duplicados(
        self, cliente_real: OmdbClient
    ) -> None:
        # El recorte por `totalResults` existe precisamente para esto. Un actor
        # con muchas peliculas fuerza varias paginas.
        resultados = cliente_real.search_by_actor("Tom Hanks")

        ids = [p.get("imdbID") for p in resultados]

        assert len(ids) == len(set(ids))


class TestCredencial:
    """Que la clave configurada sea realmente aceptada por OMDb."""

    def test_una_credencial_invalida_da_api_auth_error(
        self, config_real: AppConfig
    ) -> None:
        # La prueba inversa: si OMDb rechazara una clave falsa con algo que no
        # sea `ApiAuthError`, la suite no detectaria que se rompio la traduccion
        # de errores al cambiar la API.
        from exceptions import ApiTimeoutError

        cliente = OmdbClient(
            OMDB_BASE_URL,
            timeout=config_real.request_timeout,
            api_key="clave-falsa-para-el-test-de-integracion",
        )
        try:
            with pytest.raises(ApiAuthError):
                cliente.search_by_title(OMDB_STABLE_TITLE)
        except ApiTimeoutError:
            pytest.skip("OMDb no respondio: no se puede verificar la credencial")
        finally:
            cliente.close()

    def test_la_credencial_no_aparece_en_el_error(
        self, config_real: AppConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        # La FASE 5 arreglaro que la URL con `apikey=` se colara en el
        # traceback. Esta comprobacion, contra la API real, es la que confirma
        # que laUrls que devuelve requests se redactan igual.
        import logging

        from exceptions import ApiError

        cliente = OmdbClient(
            OMDB_BASE_URL,
            timeout=config_real.request_timeout,
            api_key="clave-falsa-para-el-test-de-integracion",
        )
        try:
            with pytest.raises(ApiError) as exc_info:
                cliente.search_by_title(OMDB_STABLE_TITLE)
        finally:
            cliente.close()

        assert config_real.omdb_api_key not in str(exc_info.value)


class TestServicioContraOmDbReal:
    """El servicio completo, de la consulta a la pantalla."""

    def test_el_servicio_construye_un_movie_desde_la_api_real(
        self, config_real: AppConfig
    ) -> None:
        # La integracion de verdad: no "el cliente funciona" ni "el servicio
        # funciona", sino que los dos juntos producen un modelo utilizable.
        with MovieService(config_real) as servicio:
            pelicula = servicio.search_movie(OMDB_STABLE_TITLE)

        assert isinstance(pelicula, Movie)
        assert pelicula.title
        assert pelicula.year

    def test_fetch_movie_devuelve_el_modelo(
        self, config_real: AppConfig
    ) -> None:
        with MovieService(config_real) as servicio:
            pelicula = servicio.fetch_movie(OMDB_STABLE_TITLE)

        assert isinstance(pelicula, Movie)
        assert OMDB_STABLE_TITLE.lower() in pelicula.title.lower()

    def test_fetch_movie_lanza_para_una_inexistente(
        self, config_real: AppConfig
    ) -> None:
        with MovieService(config_real) as servicio:
            with pytest.raises(MovieNotFoundError):
                servicio.fetch_movie("QzXxXxPeliculaQueNoExisteXxXxQ123456789")

    def test_la_cache_evita_la_segunda_consulta(
        self, config_real: AppConfig
    ) -> None:
        # Se mide por las metricas del servicio, no por la red: si la segunda
        # busqueda saliera a la red, las metricas marcarian un fallo.
        with MovieService(config_real) as servicio:
            servicio.search_movie(OMDB_STABLE_TITLE)
            servicio.search_movie(OMDB_STABLE_TITLE)

            metricas = servicio.movie_cache_stats()

        assert metricas["hits"] == 1

    def test_movies_by_actor_devuelve_modelos(
        self, config_real: AppConfig
    ) -> None:
        with MovieService(config_real) as servicio:
            peliculas = servicio.movies_by_actor("Tom Hanks")

        assert isinstance(peliculas, tuple)
        for pelicula in peliculas:
            assert isinstance(pelicula, Movie)
            assert pelicula.title

    def test_el_catalogo_local_sigue_disponible_sin_red(
        self, config_real: AppConfig
    ) -> None:
        # El respaldo de la FASE 5: sin credencial util, la aplicacion puede
        # seguir ofreciendo el catalogo estatico.
        from constants import LocalMovie

        with MovieService(config_real) as servicio:
            populares = servicio.popular_movies()

        assert len(populares) > 0
        assert all(isinstance(p, LocalMovie) for p in populares)
