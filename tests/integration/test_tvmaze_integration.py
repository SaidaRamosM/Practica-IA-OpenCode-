"""Pruebas de integracion contra TVMaze real.

TVMaze es una API publica: no necesita credencial, asi que estos tests se
ejecutan siempre que haya conexion. Aun asi van marcados como ``integration``,
porque **dependen de la red** y un unitario no puede depender de eso.

A diferencia de OMDb, aqui se comprueban mas cosas del contenido porque TVMaze es
mucho mas estable: el catalogo de series cambia muy rara vez, y `Breaking Bad`
lleva anos con los mismos identificadores.

Lo que se evita a proposito: no se comprueban valores exactos de puntuaciones
(pueden variar), ni el numero de resultados de una busqueda, ni el texto de los
resúmenes. Se comprueban presencia, forma y conversion al modelo.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from api.tvmaze import TvmazeClient
from config import AppConfig
from constants import TVMAZE_BASE_URL, TVMAZE_SHOW_FIELDS
from exceptions import ApiContractError, EmptyQueryError, SeriesNotFoundError
from models.series import Series
from services.series_service import SeriesService
from tests.conftest import TVMAZE_STABLE_SHOW

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def config_sin_clave() -> AppConfig:
    """Configuracion con clave ficticia: TVMaze no la usa, pero
    ``AppConfig`` la exige.

    Es la prueba de que la credencial es obligatoria *para arrancar* y no
    *para TVMaze*: la clave falsa no molesta porque el cliente de TVMaze no
    manda ``apikey`` en sus peticiones.
    """
    return AppConfig.from_env(
        {"OMDB_API_KEY": "ficticia-tvmaze-no-la-usa", "OMDB_TIMEOUT": "20"}
    )


@pytest.fixture
def cliente_real(config_sin_clave: AppConfig) -> TvmazeClient:
    """Cliente de TVMaze real, cerrado al terminar el test."""
    cliente = TvmazeClient(
        TVMAZE_BASE_URL, timeout=config_sin_clave.request_timeout
    )
    yield cliente
    cliente.close()


class TestBusquedaReal:
    """``/search/shows`` contra el servicio en vivo."""

    def test_encuentra_la_serie_conocida(
        self, cliente_real: TvmazeClient
    ) -> None:
        resultados = cliente_real.search_shows(TVMAZE_STABLE_SHOW)

        assert len(resultados) > 0

    def test_cada_resultado_lleva_el_envoltorio_show(
        self, cliente_real: TvmazeClient
    ) -> None:
        # El envoltorio es parte del contrato de este endpoint: sin el, la
        # serie no tendria datos.
        resultados = cliente_real.search_shows(TVMAZE_STABLE_SHOW)

        assert all("show" in resultado for resultado in resultados)

    def test_cada_show_tiene_nombre_e_id(
        self, cliente_real: TvmazeClient
    ) -> None:
        # Id y nombre son los dos campos de los que depende `find_series`.
        resultados = cliente_real.search_shows(TVMAZE_STABLE_SHOW)

        for resultado in resultados:
            show = resultado["show"]
            assert isinstance(show["name"], str) and show["name"]
            assert isinstance(show["id"], int)

    def test_los_resultados_estan_ordenados_por_relevancia(
        self, cliente_real: TvmazeClient
    ) -> None:
        # TVMaze ordena por `score` descendente. Si se desordenaran, la serie
        # buscada dejaria de ser la primera de la pantalla.
        resultados = cliente_real.search_shows(TVMAZE_STABLE_SHOW)

        puntuaciones = [r.get("score", 0) for r in resultados]

        assert puntuaciones == sorted(puntuaciones, reverse=True)

    def test_el_primer_resultado_es_el_mas_cercano(
        self, cliente_real: TvmazeClient
    ) -> None:
        resultados = cliente_real.search_shows(TVMAZE_STABLE_SHOW)

        # Buscar por el nombre exacto tiene que devolverlo el primero.
        assert TVMAZE_STABLE_SHOW.lower() in resultados[0]["show"]["name"].lower()

    def test_una_busqueda_sin_coincidencias_devuelve_lista_vacia(
        self, cliente_real: TvmazeClient
    ) -> None:
        # TVMaze responde 200 con `[]`, no un 404: el cliente tiene que
        # devolver una tupla vacia y no lanzar.
        resultados = cliente_real.search_shows("QzXxXxSerieInexistenteXxXxQ987654321")

        assert resultados == ()


class TestDetalleReal:
    """``/shows/{id}`` contra el servicio en vivo."""

    def test_el_detalle_llega_plano_sin_envoltorio(
        self, cliente_real: TvmazeClient
    ) -> None:
        # A diferencia de la busqueda, aqui el show no va envuelto. Es la
        # diferencia de forma que obliga a que `extract_show` sea idempotente.
        primero = cliente_real.search_shows(TVMAZE_STABLE_SHOW)[0]["show"]

        detalle = cliente_real.show_details(primero["id"])

        assert "show" not in detalle
        assert detalle["id"] == primero["id"]

    def test_el_detalle_trae_los_campos_de_la_pantalla(
        self, cliente_real: TvmazeClient
    ) -> None:
        # Se comprueba la presencia de las 9 rutas de `TVMAZE_SHOW_FIELDS`:
        # si TVMaze renombrara una, la tabla de la pantalla se quedaria con una
        # columna vacia y estos tests lo detectarian.
        primero = cliente_real.search_shows(TVMAZE_STABLE_SHOW)[0]["show"]

        detalle = cliente_real.show_details(primero["id"])

        for ruta, _etiqueta in TVMAZE_SHOW_FIELDS:
            # `HttpClient` devuelve los dict como `MappingProxyType`, no como
            # `dict`: el `isinstance` tiene que admitir el tipo real.
            valor: object = detalle
            for segmento in ruta.split("."):
                assert isinstance(valor, Mapping) and segmento in valor, (
                    f"TVMaze no devolvio el campo {ruta!r}"
                )
                valor = valor[segmento]

    def test_el_rating_existe_en_la_api_real(
        self, cliente_real: TvmazeClient
    ) -> None:
        primero = cliente_real.search_shows(TVMAZE_STABLE_SHOW)[0]["show"]

        detalle = cliente_real.show_details(primero["id"])

        # No se comprueba el valor, que puede variar, sino que la ruta anidada
        # existe: es la que la pantalla muestra como "Rating".
        assert "average" in detalle.get("rating", {})

    def test_el_id_se_acepta_como_cadena(
        self, cliente_real: TvmazeClient
    ) -> None:
        # El historial guarda el id como texto, y tiene que funcionar igual.
        primero = cliente_real.search_shows(TVMAZE_STABLE_SHOW)[0]["show"]

        detalle = cliente_real.show_details(str(primero["id"]))

        assert detalle["id"] == primero["id"]

    def test_un_id_inexistente_produce_un_error_de_api(
        self, cliente_real: TvmazeClient
    ) -> None:
        from exceptions import ApiError

        with pytest.raises(ApiError):
            cliente_real.show_details(99999999)

    @pytest.mark.parametrize("show_id", ["", "   ", "None"])
    def test_un_id_invalido_se_rechaza_sin_consultar(
        self, cliente_real: TvmazeClient, show_id: str
    ) -> None:
        with pytest.raises(EmptyQueryError):
            cliente_real.show_details(show_id)


class TestSinCredencial:
    """TVMaze no necesita clave, y eso tiene que ser cierto de verdad."""

    def test_el_cliente_no_manda_apikey(
        self, cliente_real: TvmazeClient
    ) -> None:
        # Se comprueba la peticion de verdad, no la configuracion: si el cliente
        # enviara `apikey` con una clave vacia, TVMaze podria rechazarlo.
        assert cliente_real._api_key is None
        assert cliente_real.search_shows(TVMAZE_STABLE_SHOW)

    def test_el_rechazo_de_id_ocurre_antes_de_la_red(
        self, cliente_real: TvmazeClient
    ) -> None:
        # Sin esto, `show_details(None)` haria una peticion a "/shows/None" y
        # devolveria un 404 en lugar de un mensaje util.
        with pytest.raises(EmptyQueryError):
            cliente_real.show_details(None)  # type: ignore[arg-type]


class TestServicioContraTvmazeReal:
    """El servicio completo, de la consulta a la pantalla."""

    def test_el_servicio_construye_series_desde_la_api_real(
        self, config_sin_clave: AppConfig
    ) -> None:
        with SeriesService(config_sin_clave) as servicio:
            series = servicio.search_series(TVMAZE_STABLE_SHOW)

        assert len(series) > 0
        assert all(isinstance(s, Series) for s in series)
        assert TVMAZE_STABLE_SHOW.lower() in series[0].title.lower()

    def test_las_series_tenen_los_campos_de_la_pantalla(
        self, config_sin_clave: AppConfig
    ) -> None:
        # El servicio normaliza el envoltorio, de modo que las propiedades
        # tipadas tienen que devolver valores, no "N/A" por todo.
        with SeriesService(config_sin_clave) as servicio:
            serie = servicio.search_series(TVMAZE_STABLE_SHOW)[0]

        assert serie.title
        assert serie.language
        assert serie.status

    def test_find_series_devuelve_el_detalle(
        self, config_sin_clave: AppConfig
    ) -> None:
        # Esta es la ruta que usa el menu: busca, coge el primero y pide su
        # detalle. Es donde se juntan los dos endpoints.
        with SeriesService(config_sin_clave) as servicio:
            serie = servicio.find_series(TVMAZE_STABLE_SHOW)

        assert isinstance(serie, Series)
        assert serie.id is not None
        assert serie.title

    def test_find_series_lanza_para_una_serie_inexistente(
        self, config_sin_clave: AppConfig
    ) -> None:
        with SeriesService(config_sin_clave) as servicio:
            with pytest.raises(SeriesNotFoundError):
                servicio.find_series("QzXxXxSerieInexistenteXxXxQ987654321")

    def test_una_busqueda_sin_coincidencias_da_tupla_vacia(
        self, config_sin_clave: AppConfig
    ) -> None:
        with SeriesService(config_sin_clave) as servicio:
            assert servicio.search_series("QzXxXxSerieInexistenteXxXxQ987654321") == ()

    def test_la_cache_evita_la_segunda_consulta(
        self, config_sin_clave: AppConfig
    ) -> None:
        with SeriesService(config_sin_clave) as servicio:
            servicio.search_series(TVMAZE_STABLE_SHOW)
            servicio.search_series(TVMAZE_STABLE_SHOW)

            metricas = servicio.series_cache_stats()

        assert metricas["hits"] == 1

    def test_el_detalle_se_cachea_por_id(
        self, config_sin_clave: AppConfig
    ) -> None:
        with SeriesService(config_sin_clave) as servicio:
            serie = servicio.find_series(TVMAZE_STABLE_SHOW)
            otra_vez = servicio.series_details(serie.id)

        # Sin consultar dos veces: el mismo id da el mismo objeto.
        assert otra_vez is serie

    def test_las_metricas_reflejan_las_consultas(
        self, config_sin_clave: AppConfig
    ) -> None:
        with SeriesService(config_sin_clave) as servicio:
            servicio.search_series(TVMAZE_STABLE_SHOW)

            metricas = servicio.series_cache_stats()

        assert metricas["entries"] >= 1
        assert metricas["misses"] >= 1
