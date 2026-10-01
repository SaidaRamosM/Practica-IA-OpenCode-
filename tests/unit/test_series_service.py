"""Pruebas de :class:`SeriesService`: la logica de negocio de series.

El servicio tiene una logica mas esposa que el de peliculas, y toda ella
concentrada en :meth:`SeriesService.find_series`, que tiene tres ramas
distintas:

1. TVMaze no devuelve nada -> ``SeriesNotFoundError``;
2. devuelve algo, pero sin objeto ``show`` -> ``ApiContractError``;
3. devuelve un ``show`` sin ``id`` -> se devuelve el resumen tal cual, sin
   pedir detalle, porque no hay con que pedirlo.

Esa tercera rama es la que mas conviene fijar con un test: es la decision de
"no fallar cuando la API devuelve algo inutil pero no invalido".

El cliente se inyecta con el parametro ``tvmaze=`` que ya existia, asi que no
hace falta ningun parche ni tocar codigo de produccion.
"""

from __future__ import annotations

from typing import Any

import pytest

from config import AppConfig
from exceptions import (
    ApiContractError,
    ApiResponseError,
    ApiTimeoutError,
    EmptyQueryError,
    SeriesNotFoundError,
)
from models.series import Series
from services.series_service import SeriesService


@pytest.fixture
def servicio(config: AppConfig, tvmaze_mock: Any) -> SeriesService:
    """``SeriesService`` con el cliente de TVMaze simulado."""
    return SeriesService(config, tvmaze=tvmaze_mock)


class TestSearchSeries:
    """``search_series``: la busqueda que desenvuelve cada resultado."""

    def test_devuelve_los_series_encontrados(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_busqueda: list[dict[str, Any]]
    ) -> None:
        # Arrange
        tvmaze_mock.search_shows.return_value = tuple(tvmaze_busqueda)

        # Act
        series = servicio.search_series("Breaking Bad")

        # Assert
        assert len(series) == 1
        assert isinstance(series[0], Series)
        assert series[0].title == "Breaking Bad"

    def test_el_envoltorio_show_queda_desenvuelto(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_busqueda: list[dict[str, Any]]
    ) -> None:
        # TVMaze envuelve en la busqueda y no en el detalle. `Series.from_payload`
        # normaliza ambas formas, asi que aqui el modelo ya va plano.
        tvmaze_mock.search_shows.return_value = tuple(tvmaze_busqueda)

        serie = servicio.search_series("Breaking Bad")[0]

        assert "show" not in serie.to_dict()
        assert serie.id == 1698

    def test_devuelve_tupla_vacia_si_no_hay_coincidencias(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        # A diferencia de `find_series`, aqui no hay excepcion: la pantalla
        # muestra un "no se encontraron" y sigue funcionando.
        tvmaze_mock.search_shows.return_value = ()

        assert servicio.search_series("Serie Inexistente") == ()

    def test_consulta_a_tvmaze_con_el_nombre_recibido(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        tvmaze_mock.search_shows.return_value = ()

        servicio.search_series("Breaking Bad")

        tvmaze_mock.search_shows.assert_called_once_with("Breaking Bad")

    def test_sirve_desde_cache_en_la_segunda_consulta(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_busqueda: list[dict[str, Any]]
    ) -> None:
        tvmaze_mock.search_shows.return_value = tuple(tvmaze_busqueda)

        servicio.search_series("Breaking Bad")
        servicio.search_series("breaking bad")

        tvmaze_mock.search_shows.assert_called_once()

    def test_un_vacio_no_se_cachea(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        # Igual que en peliculas: cachear un vacio congelaria el resultado.
        tvmaze_mock.search_shows.return_value = ()

        servicio.search_series("Serie")
        servicio.search_series("Serie")

        assert tvmaze_mock.search_shows.call_count == 2

    def test_un_error_de_red_no_se_cachea(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        tvmaze_mock.search_shows.side_effect = ApiTimeoutError("timeout")

        with pytest.raises(ApiTimeoutError):
            servicio.search_series("Breaking Bad")
        with pytest.raises(ApiTimeoutError):
            servicio.search_series("Breaking Bad")

        assert tvmaze_mock.search_shows.call_count == 2

    @pytest.mark.parametrize("nombre", ["", "   "])
    def test_rechaza_un_nombre_vacio_sin_consultar(
        self, servicio: SeriesService, tvmaze_mock: Any, nombre: str
    ) -> None:
        with pytest.raises(EmptyQueryError):
            servicio.search_series(nombre)

        tvmaze_mock.search_shows.assert_not_called()

    def test_los_atributos_del_series_son_accesibles(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_busqueda: list[dict[str, Any]]
    ) -> None:
        # Comprueba que el modelo lee bien el payload, incluidos los anidados.
        tvmaze_mock.search_shows.return_value = tuple(tvmaze_busqueda)

        serie = servicio.search_series("Breaking Bad")[0]

        assert serie.title == "Breaking Bad"
        assert serie.language == "English"
        assert serie.genres == ["Drama", "Crime"]
        assert serie.rating == "9.3"
        assert serie.status == "Ended"
        assert serie.runtime == "47"

    def test_el_resumen_conserva_el_html_de_tvmaze(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_busqueda: list[dict[str, Any]]
    ) -> None:
        # TVMaze devuelve el resumen con etiquetas `<p>`. El modelo no las quita:
        # quitarlas aqui cambiaria lo que se muestra y el JSON exportado.
        tvmaze_mock.search_shows.return_value = tuple(tvmaze_busqueda)

        assert "<p>" in servicio.search_series("Breaking Bad")[0].summary


class TestSeriesDetails:
    """``series_details``: el detalle por id, cacheado aparte."""

    def test_devuelve_el_series_del_id(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_show: dict[str, Any]
    ) -> None:
        tvmaze_mock.show_details.return_value = tvmaze_show

        serie = servicio.series_details(1698)

        assert isinstance(serie, Series)
        assert serie.title == "Breaking Bad"
        assert serie.id == 1698

    def test_acepta_el_id_como_cadena(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_show: dict[str, Any]
    ) -> None:
        # El historial guarda el id como texto; no debe hacer falta convertirlo.
        tvmaze_mock.show_details.return_value = tvmaze_show

        serie = servicio.series_details("1698")

        assert serie.id == 1698
        tvmaze_mock.show_details.assert_called_once_with("1698")

    def test_sirve_desde_cache_en_la_segunda_peticion(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_show: dict[str, Any]
    ) -> None:
        tvmaze_mock.show_details.return_value = tvmaze_show

        servicio.series_details(1698)
        servicio.series_details(1698)

        tvmaze_mock.show_details.assert_called_once()

    def test_ids_distintos_no_comparten_cache(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_show: dict[str, Any]
    ) -> None:
        tvmaze_mock.show_details.return_value = tvmaze_show

        servicio.series_details(1)
        servicio.series_details(2)

        assert tvmaze_mock.show_details.call_count == 2

    @pytest.mark.parametrize("show_id", ["", "   ", None, "None"])
    def test_rechaza_un_id_invalido_sin_consultar(
        self, servicio: SeriesService, tvmaze_mock: Any, show_id: object
    ) -> None:
        with pytest.raises(EmptyQueryError):
            servicio.series_details(show_id)  # type: ignore[arg-type]

        tvmaze_mock.show_details.assert_not_called()

    def test_un_error_de_red_se_propaga(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        tvmaze_mock.show_details.side_effect = ApiResponseError("HTTP 500")

        with pytest.raises(ApiResponseError):
            servicio.series_details(1698)

    def test_un_error_no_se_cachea(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        tvmaze_mock.show_details.side_effect = ApiResponseError("HTTP 500")

        with pytest.raises(ApiResponseError):
            servicio.series_details(1698)
        with pytest.raises(ApiResponseError):
            servicio.series_details(1698)

        assert tvmaze_mock.show_details.call_count == 2


class TestFindSeries:
    """``find_series``: las tres ramas, una por test.

    Cada rama corresponde a una forma distinta de la respuesta de TVMaze, y cada
    una tiene una accion distinta: fallar con excepcion de negocio, fallar con
    error de contrato, o devolver lo poco que hay.
    """

    def test_devuelve_el_detalle_del_primer_resultado(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_busqueda: list[dict[str, Any]], tvmaze_show: dict[str, Any]
    ) -> None:
        # Camino normal: busca, toma el primero y pide su detalle.
        tvmaze_mock.search_shows.return_value = tuple(tvmaze_busqueda)
        tvmaze_mock.show_details.return_value = tvmaze_show

        serie = servicio.find_series("Breaking Bad")

        assert serie.title == "Breaking Bad"
        # `series_details` normaliza el id a cadena antes de delegar, de modo
        # que la clave de cache no se fragmente entre `1698` y `"1698"`.
        tvmaze_mock.show_details.assert_called_once_with("1698")

    def test_toma_el_primer_resultado_cuando_hay_varios(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_busqueda: list[dict[str, Any]], tvmaze_show: dict[str, Any]
    ) -> None:
        # El primero es el mejor segun el score de TVMaze. No se recorre la
        # lista buscando uno "bueno": seria cambiar el criterio de ordenacion.
        segundo = {"show": {"id": 2000, "name": "Otra serie"}}
        tvmaze_mock.search_shows.return_value = tuple([*tvmaze_busqueda, segundo])
        tvmaze_mock.show_details.return_value = tvmaze_show

        serie = servicio.find_series("Breaking Bad")

        assert serie.id == 1698
        tvmaze_mock.show_details.assert_called_once_with("1698")

    def test_lanza_series_not_found_si_no_hay_resultados(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        tvmaze_mock.search_shows.return_value = ()

        with pytest.raises(SeriesNotFoundError):
            servicio.find_series("Serie Inexistente")

    def test_el_error_identifica_la_serie_buscada(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        tvmaze_mock.search_shows.return_value = ()

        with pytest.raises(SeriesNotFoundError) as exc_info:
            servicio.find_series("Serie Inexistente")

        assert exc_info.value.title == "Serie Inexistente"
        assert "Serie Inexistente" in str(exc_info.value)

    def test_lanza_api_contract_error_si_el_resultado_no_tiene_show(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        # TVMaze cambio de formato. No es "no encontrada" sino "no puedo
        # interpretarla": confundirlas llevaria a un "no se encontraron series"
        # cuando el problema es tecnico.
        tvmaze_mock.search_shows.return_value = ({"score": 0.5},)

        with pytest.raises(ApiContractError, match="show"):
            servicio.find_series("Breaking Bad")

    def test_lanza_api_contract_error_si_show_no_es_un_mapeo(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        tvmaze_mock.search_shows.return_value = ({"show": "texto"},)

        with pytest.raises(ApiContractError, match="show"):
            servicio.find_series("Breaking Bad")

    def test_devuelve_el_resumen_sin_id_sin_pedir_detalle(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_busqueda: list[dict[str, Any]]
    ) -> None:
        # Rama 3, la que mas conviene fijar: un show sin id no se puede ampliar,
        # pero tampoco es un fallo. Se devuelve lo que hay en vez de reventar.
        tvmaze_mock.search_shows.return_value = ({"show": {"name": "Serie sin id"}},)

        serie = servicio.find_series("Serie sin id")

        assert serie.title == "Serie sin id"
        tvmaze_mock.show_details.assert_not_called()

    def test_un_id_inexistente_no_impide_devolver_la_serie(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_busqueda: list[dict[str, Any]]
    ) -> None:
        tvmaze_mock.search_shows.return_value = ({"show": {"id": 0, "name": "Con id cero"}},)

        # El id 0 es falsy: el codigo debe distinguirlo de "no hay id" con
        # `is None`, no con un truthiness. Por eso se configura `show_details`
        # con un retorno: si el codigo lo tratara como ausente, devolveria este
        # `Mock` y la comprobacion fallaria.
        tvmaze_mock.show_details.return_value = {"id": 0, "name": "Con id cero"}

        serie = servicio.find_series("Con id cero")

        assert serie.id == 0
        # El id 0 es falsy: el codigo debe distinguirlo de "no hay id" con
        # `is None`, no con un truthiness. Por eso se configura `show_details`
        # con un retorno: si el codigo lo tratara como ausente, devolveria este
        # `Mock` y la comprobacion fallaria.
        tvmaze_mock.show_details.return_value = {"id": 0, "name": "Con id cero"}

        serie = servicio.find_series("Con id cero")

        assert serie.id == 0
        tvmaze_mock.show_details.assert_called_once_with("0")

    def test_el_no_encontrado_no_se_confunde_con_un_error_de_red(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        tvmaze_mock.search_shows.side_effect = ApiTimeoutError("timeout")

        with pytest.raises(ApiTimeoutError):
            servicio.find_series("Breaking Bad")

    def test_reutiliza_la_cache_de_la_busqueda(
        self, servicio: SeriesService, tvmaze_mock: Any, tvmaze_busqueda: list[dict[str, Any]], tvmaze_show: dict[str, Any]
    ) -> None:
        # `find_series` envuelve a `_search_payloads`, asi que un `search_series`
        # previo no debe provocar una segunda peticion de busqueda.
        tvmaze_mock.search_shows.return_value = tuple(tvmaze_busqueda)
        tvmaze_mock.show_details.return_value = tvmaze_show

        servicio.search_series("Breaking Bad")
        servicio.find_series("Breaking Bad")

        tvmaze_mock.search_shows.assert_called_once()


class TestDiagnosticoYCicloDeVida:
    """Metricas, cierre y contexto."""

    def test_las_metricas_reflejan_las_consultas(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        tvmaze_mock.search_shows.return_value = ({"show": {"id": 1, "name": "A"}},)

        servicio.search_series("A")
        servicio.search_series("A")
        servicio.search_series("B")

        metricas = servicio.series_cache_stats()
        assert metricas["hits"] == 1
        assert metricas["misses"] == 2

    def test_clear_caches_vacia_la_cache(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        tvmaze_mock.search_shows.return_value = ({"show": {"id": 1, "name": "A"}},)
        servicio.search_series("A")

        servicio.clear_caches()

        assert servicio.series_cache_stats()["entries"] == 0

    def test_el_cliente_inyectado_no_se_cierra(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        # El cliente lo creo el test: cerrarlo romperia a quien lo paso.
        servicio.close()

        tvmaze_mock.close.assert_not_called()

    def test_admite_el_gestor_de_contexto(
        self, config: AppConfig, tvmaze_mock: Any
    ) -> None:
        with SeriesService(config, tvmaze=tvmaze_mock) as servicio:
            assert isinstance(servicio, SeriesService)

    def test_expone_su_configuracion(
        self, servicio: SeriesService, config: AppConfig
    ) -> None:
        assert servicio.config is config

    def test_el_repr_no_filtra_la_credencial(self, servicio: SeriesService) -> None:
        from tests.conftest import FAKE_API_KEY

        representacion = repr(servicio)

        assert FAKE_API_KEY not in representacion
        assert "timeout" in representacion

    def test_construye_su_propio_cliente_si_no_se_inyecta_ninguno(
        self, config: AppConfig
    ) -> None:
        # El camino de produccion. No se llama a la red: solo se comprueba que
        # se puede construir sin inyeccion.
        servicio = SeriesService(config)

        assert servicio._tvmaze is not None
        servicio.close()


class TestErroresDelDominio:
    """Las excepciones del servicio cuelgan de la base del dominio."""

    def test_series_not_found_es_del_dominio(
        self, servicio: SeriesService, tvmaze_mock: Any
    ) -> None:
        from exceptions import MovieCatalogError

        tvmaze_mock.search_shows.return_value = ()

        with pytest.raises(MovieCatalogError):
            servicio.find_series("Serie Inexistente")

    def test_empty_query_error_es_del_dominio(self, servicio: SeriesService) -> None:
        from exceptions import MovieCatalogError

        with pytest.raises(MovieCatalogError):
            servicio.search_series("   ")
