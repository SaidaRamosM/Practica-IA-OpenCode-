"""Pruebas de :class:`TvmazeClient`: el formato de TVMaze, no la red.

La diferencia con OMDb que mas importa: TVMaze responde con una **lista en la
raiz** en ``/search/shows`` y con un **objeto plano** en ``/shows/{id}``, y
ademas envuelve el resultado de la busqueda en ``{"show": {...}}``. Esa doble
forma es la que se prueba aqui.

Igual que en ``test_omdb.py``, el mock es de ``HttpClient.get_json``: no existe
ningun ``requests.get`` en ``api/tvmaze.py``, y los errores de red ya estan
cubiertos en ``test_http_client.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest

from api.base import HttpClient
from api.tvmaze import TvmazeClient
from exceptions import ApiContractError, EmptyQueryError
from tests.unit.conftest import FakeResponse, FakeSession


class TestSearchShows:
    """``search_shows``: una lista en la raiz, con envoltorio ``show``."""

    def test_devuelve_los_envoltorios_sin_desenvolverlos(
        self,
        tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]],
        tvmaze_busqueda: list[dict[str, Any]],
    ) -> None:
        # El cliente NO desenvuelve: `Series.from_payload` lo hace. Si el
        # cliente lo hiciera aqui, `Series` no podria distinguir las dos formas.
        cliente, _ = tvmaze_client(FakeResponse(json_data=tvmaze_busqueda))

        resultados = cliente.search_shows("Breaking Bad")

        assert len(resultados) == 1
        assert "show" in resultados[0]
        assert resultados[0]["show"]["name"] == "Breaking Bad"

    def test_conserva_el_score_de_la_busqueda(
        self,
        tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]],
        tvmaze_busqueda: list[dict[str, Any]],
    ) -> None:
        # El score ordena los resultados; perderlo seria cambiar el
        # comportamiento de la pantalla sin darse cuenta.
        cliente, _ = tvmaze_client(FakeResponse(json_data=tvmaze_busqueda))

        assert cliente.search_shows("Breaking Bad")[0]["score"] == 0.1

    def test_devuelve_tupla_vacia_si_no_hay_coincidencias(
        self, tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]]
    ) -> None:
        cliente, _ = tvmaze_client(FakeResponse(json_data=[]))

        assert cliente.search_shows("Serie Inexistente") == ()

    def test_envia_el_nombre_como_parametro_q(
        self,
        tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]],
        tvmaze_busqueda: list[dict[str, Any]],
    ) -> None:
        cliente, sesion = tvmaze_client(FakeResponse(json_data=tvmaze_busqueda))

        cliente.search_shows("Breaking Bad")

        assert sesion.llamadas[0]["params"]["q"] == "Breaking Bad"

    def test_consulta_el_endpoint_de_busqueda(
        self,
        tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]],
        tvmaze_busqueda: list[dict[str, Any]],
    ) -> None:
        cliente, sesion = tvmaze_client(FakeResponse(json_data=tvmaze_busqueda))

        cliente.search_shows("x")

        assert sesion.llamadas[0]["url"].endswith("/search/shows")

    def test_recorta_los_espacios_del_nombre(
        self,
        tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]],
        tvmaze_busqueda: list[dict[str, Any]],
    ) -> None:
        cliente, sesion = tvmaze_client(FakeResponse(json_data=tvmaze_busqueda))

        cliente.search_shows("  Breaking Bad  ")

        assert sesion.llamadas[0]["params"]["q"] == "Breaking Bad"

    def test_no_manda_apikey_porque_tvmaze_es_publica(
        self,
        tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]],
        tvmaze_busqueda: list[dict[str, Any]],
    ) -> None:
        # A diferencia de OMDb, aqui no se inyecta ninguna credencial.
        cliente, sesion = tvmaze_client(FakeResponse(json_data=tvmaze_busqueda))

        cliente.search_shows("x")

        assert "apikey" not in sesion.llamadas[0]["params"]

    def test_un_objeto_en_lugar_de_lista_da_api_contract_error(
        self, tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]]
    ) -> None:
        # Si TVMaze devolviera un objeto aqui, el cliente no debe suponer nada:
        # es un cambio de contrato y hay que notarlo.
        cliente, _ = tvmaze_client(FakeResponse(json_data={"shows": []}))

        with pytest.raises(ApiContractError, match="se esperaba una lista"):
            cliente.search_shows("x")

    def test_descarta_los_elementos_que_no_son_objetos(
        self, tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]]
    ) -> None:
        # TVMaze podria anadir un elemento raro; se salta en vez de romper, para
        # que un solo dato corrupto no deje la pantalla vacia.
        cliente, _ = tvmaze_client(
            FakeResponse(
                json_data=[{"show": {"id": 1, "name": "A"}}, "basura", 42, None]
            )
        )

        resultados = cliente.search_shows("x")

        assert len(resultados) == 1
        assert resultados[0]["show"]["id"] == 1

    def test_acepta_una_lista_de_envoltorios_sin_show(
        self, tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]]
    ) -> None:
        # El cliente no valida el contenido del envoltorio: de eso se encarga
        # `SeriesService.find_series`, que necesita poder distinguir.
        cliente, _ = tvmaze_client(FakeResponse(json_data=[{"score": 0.5}]))

        assert cliente.search_shows("x") == ({"score": 0.5},)

    @pytest.mark.parametrize("nombre", ["", "   "])
    def test_rechaza_un_nombre_vacio_sin_llegar_a_la_red(
        self,
        tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]],
        nombre: str,
    ) -> None:
        cliente, sesion = tvmaze_client(FakeResponse(json_data=[]))

        with pytest.raises(EmptyQueryError):
            cliente.search_shows(nombre)

        assert sesion.llamadas == []


class TestShowDetails:
    """``show_details``: objeto plano y construccion de la ruta."""

    def test_devuelve_el_show_plano(
        self,
        tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]],
        tvmaze_show: dict[str, Any],
    ) -> None:
        # A diferencia de la busqueda, aqui el show viene sin envoltorio.
        cliente, _ = tvmaze_client(FakeResponse(json_data=tvmaze_show))

        resultado = cliente.show_details(1698)

        assert resultado["name"] == "Breaking Bad"
        assert "show" not in resultado

    def test_construye_la_ruta_con_el_id(
        self, tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]]
    ) -> None:
        cliente, sesion = tvmaze_client(FakeResponse(json_data={"id": 1, "name": "A"}))

        cliente.show_details(1698)

        assert sesion.llamadas[0]["url"].endswith("/shows/1698")

    def test_acepta_el_id_como_cadena(
        self, tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]]
    ) -> None:
        # El menu de configuracion y el historial pueden traerlo como texto.
        cliente, sesion = tvmaze_client(FakeResponse(json_data={"id": 1, "name": "A"}))

        cliente.show_details("1698")

        assert sesion.llamadas[0]["url"].endswith("/shows/1698")

    def test_no_manda_parametros_en_la_peticion_de_detalle(
        self, tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]]
    ) -> None:
        # `get_json` sin `params` es valido: la ruta ya lleva el id.
        cliente, sesion = tvmaze_client(FakeResponse(json_data={"id": 1, "name": "A"}))

        cliente.show_details(1)

        assert sesion.llamadas[0]["params"] == {}

    @pytest.mark.parametrize("show_id", ["", "   ", None, "None"])
    def test_rechaza_un_id_invalido_sin_llegar_a_la_red(
        self,
        tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]],
        show_id: object,
    ) -> None:
        # `str(None)` es "None": sin esta comprobacion, buscar el detalle de
        # None construiria "/shows/None" y devolveria un 404 de TVMaze.
        cliente, sesion = tvmaze_client(FakeResponse(json_data={}))

        with pytest.raises(EmptyQueryError, match="id de serie"):
            cliente.show_details(show_id)  # type: ignore[arg-type]

        assert sesion.llamadas == []

    def test_una_lista_en_vez_de_objeto_da_api_contract_error(
        self, tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]]
    ) -> None:
        cliente, _ = tvmaze_client(FakeResponse(json_data=[{"id": 1}]))

        with pytest.raises(ApiContractError, match="se esperaba un objeto"):
            cliente.show_details(1)

    def test_el_endpoint_del_error_usa_la_ruta_del_show(
        self, tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]]
    ) -> None:
        # El endpoint del error debe ser la ruta concreta, no la base: asi se
        # sabe que serie fallo sin mirar el log.
        cliente, _ = tvmaze_client(FakeResponse(json_data=[{"id": 1}]))

        with pytest.raises(ApiContractError) as exc_info:
            cliente.show_details(1698)

        assert exc_info.value.endpoint == "/shows/1698"


class TestJerarquiaDelCliente:
    """Propiedades estructurales, no logica."""

    def test_tvmaze_client_es_un_http_client(self) -> None:
        assert issubclass(TvmazeClient, HttpClient)

    def test_es_un_cliente_con_gestor_de_contexto(self) -> None:
        with TvmazeClient("https://api.invalid", timeout=1.0) as cliente:
            assert isinstance(cliente, TvmazeClient)

    def test_se_crea_sin_clave_por_defecto(self) -> None:
        # TVMaze es publica: el cliente tiene que poder funcionar sin credencial.
        cliente = TvmazeClient("https://api.invalid", timeout=1.0)

        assert cliente._api_key is None

    def test_el_endpoint_de_busqueda_usa_una_forma_distinta_al_de_omdb(
        self, tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]]
    ) -> None:
        # Comprueba que la ruta con barra inicial se une bien a la base, que en
        # TVMAZE_BASE_URL no lleva barra final.
        cliente, sesion = tvmaze_client(FakeResponse(json_data=[]))

        cliente.search_shows("x")

        assert sesion.llamadas[0]["url"] == "https://api.tvmaze.com/search/shows"


class TestAmbasFormasDelShow:
    """La propiedad que hace que ``Series`` tenga sentido."""

    def test_busqueda_y_detalle_dan_formas_distintas(
        self,
        tvmaze_client: Callable[..., tuple[TvmazeClient, FakeSession]],
        tvmaze_show: Mapping[str, Any],
    ) -> None:
        # Documenta el contrato real de la API: no es un detalle del cliente,
        # es la razon de que `extract_show` tenga que ser idempotente.
        cliente, _ = tvmaze_client(FakeResponse(json_data=[{"show": dict(tvmaze_show)}]))
        resultados = cliente.search_shows("Breaking Bad")
        cliente2, _ = tvmaze_client(FakeResponse(json_data=dict(tvmaze_show)))
        detalle = cliente2.show_details(1698)

        assert "show" in resultados[0]
        assert "show" not in detalle
        assert resultados[0]["show"] == detalle
