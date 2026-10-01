"""Pruebas de :class:`MovieService`: la logica de negocio de peliculas.

Aqui ya no hay formato de API, hay reglas: que se cachea, que no, cuando se
lanza excepcion y cuando se devuelve ``None``.

El cliente de OMDb se inyecta con el parametro ``omdb=`` que ya tenia
``MovieService.__init__``, de modo que estos tests no tocan la red. No hace
falto ningun parche: el punto de inyeccion existia antes de esta fase.

Dos comportamientos merecen atencion especial, porque son los que la FASE 3
corrigio y los que un test ingenuo pasaria por alto:

* un "no encontrado" **no** se cachea, pero un acierto si;
* la excepcion de error de red **no** se cachea, para que un reintento
  posterior pueda funcionar.
"""

from __future__ import annotations

from typing import Any

import pytest

from cache import TTLCache
from config import AppConfig
from constants import GENRE_LABELS, LocalMovie
from exceptions import (
    ApiConnectionError,
    ApiResponseError,
    ApiTimeoutError,
    EmptyQueryError,
    MovieCatalogError,
    MovieNotFoundError,
)
from models.movie import Movie
from services.movie_service import MovieService


@pytest.fixture
def servicio(config: AppConfig, omdb_mock: Any) -> MovieService:
    """``MovieService`` con el cliente de OMDb simulado.

    La sesion que devuelve la fixture ``config`` tiene ``cache_max_entries=2``,
    suficiente para que los tests de cache funcionen sin insertar 256 entradas.
    """
    return MovieService(config, omdb=omdb_mock)


class TestSearchMovie:
    """``search_movie``: el camino de consulta mas usado."""

    def test_devuelve_un_movie_cuando_omdb_encuentra(
        self,
        servicio: MovieService,
        omdb_mock: Any,
        omdb_pelicula_encontrada: dict[str, Any],
    ) -> None:
        # Arrange
        omdb_mock.search_by_title.return_value = omdb_pelicula_encontrada

        # Act
        pelicula = servicio.search_movie("Interstellar")

        # Assert
        assert isinstance(pelicula, Movie)
        assert pelicula.title == "Interstellar"
        assert pelicula.year == "2014"
        # `Movie` no nombra el id de IMDb como propiedad: se lee por ruta, que
        # es el acceso que usa la capa de presentacion.
        assert pelicula.get("imdbID") == "tt0816692"

    def test_devuelve_none_cuando_omdb_no_encuentra(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        # None y no excepcion: la interfaz distingue "no existe" de "la red
        # fallo" sin capturar nada.
        omdb_mock.search_by_title.return_value = None

        assert servicio.search_movie("Pelicula Inexistente") is None

    def test_consulta_a_omdb_con_el_titulo_recibido(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_title.return_value = None

        servicio.search_movie("Interstellar")

        omdb_mock.search_by_title.assert_called_once_with("Interstellar")

    def test_el_titulo_se_recorta_antes_de_consultar(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_title.return_value = None

        servicio.search_movie("  Interstellar  ")

        omdb_mock.search_by_title.assert_called_once_with("Interstellar")

    @pytest.mark.parametrize("titulo", ["", "   "])
    def test_rechaza_un_titulo_vacio_sin_consultar(
        self, servicio: MovieService, omdb_mock: Any, titulo: str
    ) -> None:
        with pytest.raises(EmptyQueryError):
            servicio.search_movie(titulo)

        omdb_mock.search_by_title.assert_not_called()

    def test_servida_desde_cache_en_la_segunda_consulta(
        self,
        servicio: MovieService,
        omdb_mock: Any,
        omdb_pelicula_encontrada: dict[str, Any],
    ) -> None:
        # La cache es el motivo de que exista el servicio. Si esto falla, cada
        # pulsacion del menu consume una peticion de la cuota de OMDb.
        omdb_mock.search_by_title.return_value = omdb_pelicula_encontrada
        primera = servicio.search_movie("Interstellar")
        segunda = servicio.search_movie("Interstellar")

        omdb_mock.search_by_title.assert_called_once()
        assert segunda is primera

    def test_la_clave_de_cache_ignora_mayusculas(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        # "Matrix" y "matrix" son la misma pelicula; buscarlas dos veces
        # desperdiciaria la cuota de la API.
        omdb_mock.search_by_title.return_value = {"Title": "Matrix", "Year": "1999"}

        servicio.search_movie("Matrix")
        servicio.search_movie("matrix")

        omdb_mock.search_by_title.assert_called_once()

    def test_titulos_distintos_no_comparten_cache(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_title.return_value = {"Title": "X", "Year": "1"}

        servicio.search_movie("Matrix")
        servicio.search_movie("Inception")

        assert omdb_mock.search_by_title.call_count == 2

    def test_un_no_encontrado_no_se_cachea(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        # El defecto que corrigio la FASE 3: cachear tambien los fallos
        # congelaba un "no existe" durante toda la sesion, aunque la pelicula
        # se añadiera al catalogo de OMDb ese mismo dia.
        omdb_mock.search_by_title.return_value = None

        servicio.search_movie("Pelicula Rara")
        servicio.search_movie("Pelicula Rara")

        assert omdb_mock.search_by_title.call_count == 2

    def test_un_error_de_red_no_se_cachea(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        # Si el error quedara cacheado, un fallo transitorio de OMDb impediria
        # consultar esa pelicula durante el resto de la sesion.
        omdb_mock.search_by_title.side_effect = ApiTimeoutError("se agoto el tiempo")

        with pytest.raises(ApiTimeoutError):
            servicio.search_movie("Interstellar")
        with pytest.raises(ApiTimeoutError):
            servicio.search_movie("Interstellar")

        assert omdb_mock.search_by_title.call_count == 2

    @pytest.mark.parametrize(
        "error",
        [
            ApiTimeoutError("timeout"),
            ApiConnectionError("sin conexion"),
            ApiResponseError("HTTP 500"),
        ],
    )
    def test_los_errores_de_api_se_propagan_sin_traducir(
        self, servicio: MovieService, omdb_mock: Any, error: Exception
    ) -> None:
        # El servicio no captura: quien sabe que reintentar y quien no, es el
        # servicio de la capa superior. Envolverlo aqui perderia el tipo.
        omdb_mock.search_by_title.side_effect = error

        with pytest.raises(type(error)):
            servicio.search_movie("Interstellar")

    def test_un_error_no_prevenido_tambien_se_propaga(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        # Si el cliente simulado falla con algo raro, el servicio no debe
        # tragarselo: callar un falloUnknown deja la pantalla vacia sin motivo.
        omdb_mock.search_by_title.side_effect = RuntimeError("fallo inesperado")

        with pytest.raises(RuntimeError):
            servicio.search_movie("Interstellar")

    def test_registra_el_titulo_de_la_pelicula_encontrada(
        self,
        servicio: MovieService,
        omdb_mock: Any,
        omdb_pelicula_encontrada: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        omdb_mock.search_by_title.return_value = omdb_pelicula_encontrada

        with caplog.at_level(logging.INFO, logger="services.movie_service"):
            servicio.search_movie("Interstellar")

        assert "Interstellar" in caplog.text

    def test_el_payload_original_no_se_transforma(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        # `Movie` envuelve el payload en vez de sustituirlo: es lo que mantiene
        # la salida por pantalla y el JSON exportado identicos.
        crudo = {"Title": "Interstellar", "Year": "2014", "ClaveRara": "valor"}
        omdb_mock.search_by_title.return_value = crudo

        pelicula = servicio.search_movie("Interstellar")

        assert pelicula.to_dict() == crudo


class TestFetchMovie:
    """``fetch_movie``: la variante que lanza excepcion."""

    def test_devuelve_el_movie_si_lo_encuentra(
        self,
        servicio: MovieService,
        omdb_mock: Any,
        omdb_pelicula_encontrada: dict[str, Any],
    ) -> None:
        omdb_mock.search_by_title.return_value = omdb_pelicula_encontrada

        pelicula = servicio.fetch_movie("Interstellar")

        assert isinstance(pelicula, Movie)
        assert pelicula.title == "Interstellar"

    def test_lanza_movie_not_found_si_no_lo_encuentra(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_title.return_value = None

        with pytest.raises(MovieNotFoundError):
            servicio.fetch_movie("Pelicula Inexistente")

    def test_el_error_identifica_la_pelicula_buscada(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_title.return_value = None

        with pytest.raises(MovieNotFoundError) as exc_info:
            servicio.fetch_movie("Pelicula Inexistente")

        assert exc_info.value.title == "Pelicula Inexistente"

    def test_el_no_encontrado_no_se_confunde_con_un_error_de_red(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        # La distincion que la interfaz necesita: "no existe" permite seguir
        # con otra busqueda, un error de red no.
        omdb_mock.search_by_title.side_effect = ApiConnectionError("sin conexion")

        with pytest.raises(ApiConnectionError):
            servicio.fetch_movie("Interstellar")

    def test_aprovecha_la_cache_de_search_movie(
        self,
        servicio: MovieService,
        omdb_mock: Any,
        omdb_pelicula_encontrada: dict[str, Any],
    ) -> None:
        # No hace su propia peticion: envuelve a `search_movie`.
        omdb_mock.search_by_title.return_value = omdb_pelicula_encontrada

        servicio.fetch_movie("Interstellar")
        servicio.fetch_movie("Interstellar")

        omdb_mock.search_by_title.assert_called_once()


class TestMoviesByActor:
    """``movies_by_actor``: resultados multiples y su cache."""

    def test_devuelve_los_movie_del_actor(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_actor.return_value = (
            {"Title": "A", "Year": "1999"},
            {"Title": "B", "Year": "2000"},
        )

        peliculas = servicio.movies_by_actor("Actor")

        assert len(peliculas) == 2
        assert [p.title for p in peliculas] == ["A", "B"]
        assert all(isinstance(p, Movie) for p in peliculas)

    def test_devuelve_tupla_vacia_si_no_hay_peliculas(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_actor.return_value = ()

        assert servicio.movies_by_actor("Actor Inexistente") == ()

    def test_sirve_desde_cache_en_la_segunda_consulta(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_actor.return_value = ({"Title": "A", "Year": "1999"},)

        servicio.movies_by_actor("Actor")
        servicio.movies_by_actor("actor")

        omdb_mock.search_by_actor.assert_called_once()

    def test_un_vacio_no_se_cachea(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        # Igual que con las peliculas: cachear un vacio congelaria un "no
        # hay peliculas de este actor" que puede desaparecer.
        omdb_mock.search_by_actor.return_value = ()

        servicio.movies_by_actor("Actor")
        servicio.movies_by_actor("Actor")

        assert omdb_mock.search_by_actor.call_count == 2

    def test_un_error_de_red_no_se_cachea(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_actor.side_effect = ApiResponseError("HTTP 500")

        with pytest.raises(ApiResponseError):
            servicio.movies_by_actor("Actor")
        with pytest.raises(ApiResponseError):
            servicio.movies_by_actor("Actor")

        assert omdb_mock.search_by_actor.call_count == 2

    @pytest.mark.parametrize("actor", ["", "   "])
    def test_rechaza_un_actor_vacio_sin_consultar(
        self, servicio: MovieService, omdb_mock: Any, actor: str
    ) -> None:
        with pytest.raises(EmptyQueryError):
            servicio.movies_by_actor(actor)

        omdb_mock.search_by_actor.assert_not_called()

    def test_las_peliculas_y_los_titulos_no_comparten_cache(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        # Son dos prefijos distintos en la misma cache: sin ellos, buscar
        # "Matrix" como actor devolveria peliculas de "Matrix" como titulo.
        omdb_mock.search_by_title.return_value = {"Title": "Matrix", "Year": "1999"}
        omdb_mock.search_by_actor.return_value = ({"Title": "Otra", "Year": "2000"},)

        servicio.search_movie("Matrix")
        peliculas = servicio.movies_by_actor("Matrix")

        assert [p.title for p in peliculas] == ["Otra"]


class TestCatalogoLocal:
    """El catalogo local no toca la red en ningun momento."""

    def test_popular_movies_no_consulta_omdb(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        populares = servicio.popular_movies()

        assert len(populares) > 0
        omdb_mock.search_by_title.assert_not_called()
        omdb_mock.search_by_actor.assert_not_called()

    def test_las_peliculas_populares_son_del_tipo_correcto(
        self, servicio: MovieService
    ) -> None:
        # `LocalMovie`, no `Movie`: no vienen de OMDb y no llevan `imdbID`.
        assert all(isinstance(p, LocalMovie) for p in servicio.popular_movies())

    def test_popular_movies_es_estable_entre_llamadas(
        self, servicio: MovieService
    ) -> None:
        assert servicio.popular_movies() == servicio.popular_movies()

    @pytest.mark.parametrize("genero", list(GENRE_LABELS))
    def test_movies_by_genre_devuelve_peliculas_del_genero(
        self, servicio: MovieService, genero: str
    ) -> None:
        peliculas = servicio.movies_by_genre(genero)

        assert len(peliculas) > 0
        assert all(isinstance(p, LocalMovie) for p in peliculas)

    def test_movies_by_genre_acepta_minusculas_y_espacios(
        self, servicio: MovieService
    ) -> None:
        # El menu fuerza minusculas, pero el metodo es publico.
        assert servicio.movies_by_genre("  ACCION ") == servicio.movies_by_genre("accion")

    def test_un_genero_desconocido_devuelve_el_catalogo_completo(
        self, servicio: MovieService
    ) -> None:
        # Comportamiento heredado del `if/elif/else` original: antes de fallar,
        # se ofrecian todas las peliculas. Es la decision correcta para un
        # catalogo de respaldo.
        total = len(servicio.movies_by_genre("accion")) + len(
            servicio.movies_by_genre("comedia")
        ) + len(servicio.popular_movies())

        assert len(servicio.movies_by_genre("genero-inexistente")) == total

    def test_el_catalogo_local_no_consulta_omdb(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        servicio.popular_movies()
        servicio.movies_by_genre("accion")

        omdb_mock.search_by_title.assert_not_called()
        omdb_mock.search_by_actor.assert_not_called()

    def test_available_genres_escribe_los_generos_del_catalogo(
        self, servicio: MovieService
    ) -> None:
        assert servicio.available_genres() == GENRE_LABELS


class TestDiagnostico:
    """Metricas y limpieza de cache."""

    def test_las_metricas_reflejan_las_consultas(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_title.return_value = {"Title": "Matrix", "Year": "1999"}

        servicio.search_movie("Matrix")
        servicio.search_movie("Matrix")
        servicio.search_movie("Inception")

        metricas = servicio.movie_cache_stats()
        assert metricas["hits"] == 1
        assert metricas["misses"] == 2
        assert metricas["entries"] == 2

    def test_las_caches_de_peliculas_y_catalogo_se_miden_por_separado(
        self, servicio: MovieService
    ) -> None:
        # Las dos caches son distintas y el menu 8 las muestra por separado.
        assert servicio.movie_cache_stats() is not servicio.local_cache_stats()
        assert set(servicio.local_cache_stats()) >= {"entries", "hits", "misses"}

    def test_clear_caches_vacia_pero_conserva_las_metricas(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_title.return_value = {"Title": "Matrix", "Year": "1999"}
        servicio.search_movie("Matrix")
        antes = servicio.movie_cache_stats()

        servicio.clear_caches()

        despues = servicio.movie_cache_stats()
        assert despues["entries"] == 0
        # Las metricas son acumuladas de la sesion: borrarlas haria perder el
        # historial en la pantalla de estadisticas.
        assert despues["hits"] == antes["hits"]

    def test_despues_de_limpiar_vuelve_a_consultar(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_title.return_value = {"Title": "Matrix", "Year": "1999"}
        servicio.search_movie("Matrix")

        servicio.clear_caches()
        servicio.search_movie("Matrix")

        assert omdb_mock.search_by_title.call_count == 2


class TestCicloDeVida:
    """Construccion, cierre y contexto."""

    def test_el_cliente_inyectado_no_se_cierra(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        # El cliente lo creo el test, no el servicio: cerrarlo seria romper a
        # quien lo paso. La comprobacion va contra el doble, no contra la red.
        servicio.close()

        omdb_mock.close.assert_not_called()

    def test_admite_el_gestor_de_contexto(
        self, config: AppConfig, omdb_mock: Any
    ) -> None:
        with MovieService(config, omdb=omdb_mock) as servicio:
            assert isinstance(servicio, MovieService)

    def test_expone_su_configuracion(self, servicio: MovieService, config: AppConfig) -> None:
        assert servicio.config is config

    def test_el_repr_no_filtra_la_credencial(self, servicio: MovieService) -> None:
        # El timeout si aparece: ayuda a depurar. La clave nunca.
        from tests.conftest import FAKE_API_KEY

        representacion = repr(servicio)

        assert FAKE_API_KEY not in representacion
        assert "timeout" in representacion

    def test_construye_su_propio_cliente_si_no_se_inyecta_ninguno(
        self, config: AppConfig
    ) -> None:
        # El camino de produccion: sin inyeccion, crea un OmdbClient real. Solo
        # se comprueba la construccion, no se llama a la red.
        servicio = MovieService(config)

        assert isinstance(servicio._omdb, type(servicio._omdb))
        servicio.close()


class TestJerarquiaDeErrores:
    """Las excepciones del servicio son del dominio, no de la libreria."""

    def test_movie_not_found_es_del_dominio(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_title.return_value = None

        with pytest.raises(MovieCatalogError):
            servicio.fetch_movie("Pelicula Inexistente")

    def test_empty_query_error_es_del_dominio(self, servicio: MovieService) -> None:
        with pytest.raises(MovieCatalogError):
            servicio.search_movie("   ")

    def test_los_errores_de_api_son_del_dominio_tambien(
        self, servicio: MovieService, omdb_mock: Any
    ) -> None:
        omdb_mock.search_by_title.side_effect = ApiTimeoutError("timeout")

        with pytest.raises(MovieCatalogError):
            servicio.search_movie("Interstellar")


class TestCacheInyectada:
    """La cache se puede sustituir, lo que la hace determinista."""

    def test_una_entrada_caducada_fuerza_una_consulta_nueva(
        self, config: AppConfig, omdb_mock: Any, reloj_falso: Any
    ) -> None:
        # Con reloj real habria que esperar; con el inyectado, no. Se comprueba
        # que la cache de peliculas respeta el TTL que le puso la configuracion.
        omdb_mock.search_by_title.return_value = {"Title": "Matrix", "Year": "1999"}
        servicio = MovieService(
            config.with_overrides(cache_ttl_seconds=1), omdb=omdb_mock
        )
        # Se sustituye el reloj de la cache interna por uno controlable.
        servicio._movie_cache._clock = reloj_falso

        servicio.search_movie("Matrix")
        reloj_falso.avanza(2)
        servicio.search_movie("Matrix")

        assert omdb_mock.search_by_title.call_count == 2

    def test_una_entrada_no_caducada_no_fuerza_una_consulta(
        self, config: AppConfig, omdb_mock: Any, reloj_falso: Any
    ) -> None:
        omdb_mock.search_by_title.return_value = {"Title": "Matrix", "Year": "1999"}
        servicio = MovieService(
            config.with_overrides(cache_ttl_seconds=60), omdb=omdb_mock
        )
        servicio._movie_cache._clock = reloj_falso

        servicio.search_movie("Matrix")
        reloj_falso.avanza(10)
        servicio.search_movie("Matrix")

        assert omdb_mock.search_by_title.call_count == 1

    def test_la_expulsion_por_tamano_libera_la_entrance_mas_antigua(
        self, config: AppConfig, omdb_mock: Any
    ) -> None:
        # `cache_max_entries=2` en la fixture. Con tres peliculas distintas, la
        # primera se expulsa y volver a buscarla vuelve a consultar OMDb.
        omdb_mock.search_by_title.return_value = {"Title": "X", "Year": "1"}
        servicio = MovieService(config, omdb=omdb_mock)

        servicio.search_movie("A")
        servicio.search_movie("B")
        servicio.search_movie("C")
        servicio.search_movie("A")

        assert omdb_mock.search_by_title.call_count == 4

    def test_la_cache_usa_ttlcache(
        self, servicio: MovieService
    ) -> None:
        # Documenta el tipo: si alguien lo cambiara, estos tests de cache
        # seguirian pasando sin avisar de que la garantia se perdio.
        assert isinstance(servicio._movie_cache, TTLCache)
