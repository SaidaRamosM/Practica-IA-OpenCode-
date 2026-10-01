"""Pruebas de :class:`OmdbClient`: el formato de OMDb, no la red.

``OmdbClient`` no tiene logica de negocio, tiene *conocimiento de un formato*:
la marca ``Response`` que distingue acierto de fallo, la paginacion de 10 en 10
de las busquedas por actor y el recorte por ``totalResults``. Eso es lo que se
prueba aqui.

El nivel de mock es ``HttpClient.get_json``, no ``requests.get``. La razon es
concreta: ``api/omdb.py`` nunca llama a ``requests.get``, todo pasa por
``HttpClient`` -> ``Session.get``. Parchear donde no se usa no surte efecto, y
ademas mezclaaria la traduccion de errores de red (que ya cubre
``test_http_client.py``) con la logica de este modulo.

De los tests de error que si merecen su sitio aqui estan los que nacen de como
es OMDb en concreto: su ``Search`` con un tipo raro, su paginacion que se pasa
de la cuenta, y su ``Response=False`` con un ``Error`` que hay que registrar.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from api.base import HttpClient
from api.omdb import OmdbClient
from exceptions import ApiContractError, EmptyQueryError, MovieNotFoundError
from tests.unit.conftest import FakeResponse, FakeSession


class TestSearchByTitle:
    """``search_by_title``: la marca ``Response`` decide si hay resultado."""

    def test_devuelve_el_payload_cuando_response_es_true(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_pelicula_encontrada: dict[str, Any],
    ) -> None:
        # Arrange
        cliente, _ = omdb_client(FakeResponse(json_data=omdb_pelicula_encontrada))

        # Act
        resultado = cliente.search_by_title("Interstellar")

        # Assert
        assert resultado is not None
        assert resultado["Title"] == "Interstellar"

    def test_devuelve_none_cuando_response_es_false(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_pelicula_no_encontrada: dict[str, Any],
    ) -> None:
        # OMDb responde 200 con `Response: "False"` cuando no encuentra nada. Es
        # un "no" y no un error: de ahi el None en vez de una excepcion.
        cliente, _ = omdb_client(FakeResponse(json_data=omdb_pelicula_no_encontrada))

        assert cliente.search_by_title("Pelicula Inexistente") is None

    def test_envia_el_titulo_como_parametro_t(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_pelicula_encontrada: dict[str, Any],
    ) -> None:
        cliente, sesion = omdb_client(FakeResponse(json_data=omdb_pelicula_encontrada))

        cliente.search_by_title("Interstellar")

        assert sesion.llamadas[0]["params"]["t"] == "Interstellar"

    def test_recorta_los_espacios_del_titulo(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_pelicula_encontrada: dict[str, Any],
    ) -> None:
        cliente, sesion = omdb_client(FakeResponse(json_data=omdb_pelicula_encontrada))

        cliente.search_by_title("  Interstellar  ")

        assert sesion.llamadas[0]["params"]["t"] == "Interstellar"

    @pytest.mark.parametrize("titulo", ["", "   "])
    def test_rechaza_un_titulo_vacio_sin_llegar_a_la_red(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        titulo: str,
    ) -> None:
        cliente, sesion = omdb_client(FakeResponse(json_data={}))

        with pytest.raises(EmptyQueryError):
            cliente.search_by_title(titulo)

        assert sesion.llamadas == []

    def test_registra_el_motivo_del_fallo(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_pelicula_no_encontrada: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # El `Error` que devuelve OMDb ("Movie not found!") es informacion
        # util para depurar. Comprobarlo aqui evita que se pierda por el camino.
        import logging

        cliente, _ = omdb_client(FakeResponse(json_data=omdb_pelicula_no_encontrada))

        with caplog.at_level(logging.DEBUG, logger="api.omdb"):
            cliente.search_by_title("Pelicula Inexistente")

        assert "Movie not found!" in caplog.text

    def test_un_objeto_en_vez_de_ficha_da_api_contract_error(
        self, omdb_client: Callable[..., tuple[OmdbClient, FakeSession]]
    ) -> None:
        # Si OMDb cambiara su formato, el error tiene que ser de contrato y no
        # un "no encontrado" silencioso.
        cliente, _ = omdb_client(FakeResponse(json_data=[{"Title": "x"}]))

        with pytest.raises(ApiContractError, match="se esperaba un objeto"):
            cliente.search_by_title("x")

    def test_acepta_el_resultado_sin_transformar(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_pelicula_encontrada: dict[str, Any],
    ) -> None:
        # El cliente devuelve el payload tal cual. Convertirlo en modelo es
        # tarea de MovieService, y duplicar la conversion aqui seria perder la
        # unica fuente de verdad sobre el formato.
        cliente, _ = omdb_client(FakeResponse(json_data=omdb_pelicula_encontrada))

        resultado = cliente.search_by_title("Interstellar")

        assert resultado is not None
        assert set(omdb_pelicula_encontrada) <= set(resultado)


class TestSearchByActor:
    """``search_by_actor``: paginacion y recorte, la parte con mas logica."""

    def test_devuelve_los_resultados_de_una_sola_pagina(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_busqueda_actor_pagina_1: dict[str, Any],
    ) -> None:
        # 3 anunciados y 3 devueltos: se para en la primera pagina.
        cliente, _ = omdb_client(FakeResponse(json_data=omdb_busqueda_actor_pagina_1))

        resultados = cliente.search_by_actor("Actor")

        assert len(resultados) == 3
        assert resultados[0]["Title"] == "A"

    def test_pide_la_pagina_siguiente_hasta_completar_el_total(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_busqueda_actor_pagina_1: dict[str, Any],
        omdb_busqueda_actor_pagina_2: dict[str, Any],
    ) -> None:
        # OMDb pagina de 10 en 10, asi que un actor con pocos resultados cabe en
        # una sola pagina. Con 6 hacen falta dos, y el bucle tiene que seguirlas.
        primera = dict(omdb_busqueda_actor_pagina_1, totalResults="6")
        segunda = dict(omdb_busqueda_actor_pagina_2, totalResults="6")

        def handler(_url: str, params: dict[str, str]) -> FakeResponse:
            return FakeResponse(
                json_data=primera if params["page"] == "1" else segunda
            )

        cliente, _ = omdb_client(handler=handler)

        resultados = cliente.search_by_actor("Actor")

        assert len(resultados) == 6
        assert [r["Title"] for r in resultados] == ["A", "B", "C", "D", "E", "F"]

    def test_recorta_el_exceso_que_anuncia_el_servidor(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_busqueda_actor_pagina_1: dict[str, Any],
    ) -> None:
        # OMDb anuncia menos de los que trae la pagina. Sin el recorte,
        # `search_by_actor` devolveria resultados de mas.
        pagina_con_exceso = dict(omdb_busqueda_actor_pagina_1, totalResults="2")
        cliente, _ = omdb_client(FakeResponse(json_data=pagina_con_exceso))

        resultados = cliente.search_by_actor("Actor")

        assert len(resultados) == 2

    def test_pide_la_pagina_1_siendo_la_primera_peticion(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_busqueda_actor_pagina_1: dict[str, Any],
    ) -> None:
        cliente, sesion = omdb_client(FakeResponse(json_data=omdb_busqueda_actor_pagina_1))

        cliente.search_by_actor("Actor")

        params = sesion.llamadas[0]["params"]
        assert params["s"] == "Actor"
        assert params["page"] == "1"
        assert params["type"] == "movie"

    def test_filtra_a_peliculas_en_la_peticion(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_busqueda_actor_pagina_1: dict[str, Any],
    ) -> None:
        # `type=movie` es lo que impide que aparezcan series de television.
        cliente, sesion = omdb_client(FakeResponse(json_data=omdb_busqueda_actor_pagina_1))

        cliente.search_by_actor("Actor")

        assert sesion.llamadas[0]["params"]["type"] == "movie"

    def test_devuelve_tupla_vacia_si_no_hay_resultados(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_pelicula_no_encontrada: dict[str, Any],
    ) -> None:
        # Response=False con Search ausente es el "no hay actor con ese nombre".
        cliente, _ = omdb_client(FakeResponse(json_data=omdb_pelicula_no_encontrada))

        assert cliente.search_by_actor("Actor Inexistente") == ()

    def test_devuelve_tupla_vacia_si_search_viene_vacio(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
    ) -> None:
        # Response=True pero sin resultados: un caso raro, que no debe colgar.
        cliente, _ = omdb_client(FakeResponse(json_data={"Search": [], "Response": "True"}))

        assert cliente.search_by_actor("Actor") == ()

    def test_un_totalresults_ilegible_no_rompe_el_cliente(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_busqueda_actor_pagina_1: dict[str, Any],
    ) -> None:
        # Sin total legible, el bucle no puede saber cuando parar por comparacion
        # de cantidad: se guia por `Search` vacio. Aqui la sesion simulada
        # devuelve siempre la misma pagina, de modo que el unico freno es el
        # tope defensivo de paginas. Lo relevante es que no se cuelgue ni
        # reviente: termina y devuelve lo que trajo.
        pagina = dict(omdb_busqueda_actor_pagina_1, totalResults="muchos")
        cliente, sesion = omdb_client(FakeResponse(json_data=pagina))

        resultados = cliente.search_by_actor("Actor")

        from constants import OMDB_MAX_SEARCH_PAGES

        assert len(sesion.llamadas) == OMDB_MAX_SEARCH_PAGES
        assert len(resultados) == 3 * OMDB_MAX_SEARCH_PAGES

    def test_el_bucle_para_solo_con_search_vacio_si_no_hay_total(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_busqueda_actor_pagina_1: dict[str, Any],
    ) -> None:
        # El caso real de un total ilegible: la ultima pagina llega vacia, y ahi
        # se detiene. Se comprueba con un total ausente en vez de ilegible,
        # porque es la forma en que `_as_int` devuelve None.
        primera = dict(omdb_busqueda_actor_pagina_1)
        primera.pop("totalResults")
        ultima = {"Search": [], "Response": "True"}

        def handler(_url: str, params: dict[str, str]) -> FakeResponse:
            return FakeResponse(json_data=primera if params["page"] == "1" else ultima)

        cliente, sesion = omdb_client(handler=handler)

        resultados = cliente.search_by_actor("Actor")

        assert len(sesion.llamadas) == 2
        assert len(resultados) == 3

    def test_descarta_los_elementos_de_search_que_no_son_objetos(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_busqueda_actor_pagina_1: dict[str, Any],
    ) -> None:
        # Un elemento raro se salta; un Search entero del tipo equivocado es un
        # cambio de contrato y si se Avisa.
        pagina = dict(
            omdb_busqueda_actor_pagina_1,
            Search=[{"Title": "A"}, "basura", 42, {"Title": "B"}],
            totalResults="2",
        )
        cliente, _ = omdb_client(FakeResponse(json_data=pagina))

        resultados = cliente.search_by_actor("Actor")

        assert [r["Title"] for r in resultados] == ["A", "B"]

    def test_un_search_con_tipo_equivocado_da_api_contract_error(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
    ) -> None:
        # Si `Search` deja de ser una lista, es que la API cambio. Callarse
        # devolveria cero peliculas sin explicar por que.
        cliente, _ = omdb_client(
            FakeResponse(json_data={"Search": {"a": 1}, "Response": "True"})
        )

        with pytest.raises(ApiContractError, match="Search"):
            cliente.search_by_actor("Actor")

    def test_una_cadena_en_search_no_cuenta_como_lista(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
    ) -> None:
        # `str` es una Sequence, asi que sin el descarte explicito "abc" se
        # recorreria como tres caracteres sueltos.
        cliente, _ = omdb_client(
            FakeResponse(json_data={"Search": "abc", "Response": "True"})
        )

        with pytest.raises(ApiContractError, match="Search"):
            cliente.search_by_actor("Actor")

    @pytest.mark.parametrize("actor", ["", "   "])
    def test_rechaza_un_actor_vacio_sin_llegar_a_la_red(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        actor: str,
    ) -> None:
        cliente, sesion = omdb_client(FakeResponse(json_data={}))

        with pytest.raises(EmptyQueryError):
            cliente.search_by_actor(actor)

        assert sesion.llamadas == []

    def test_el_tope_de_paginas_impide_un_bucle_infinito(
        self, omdb_client: Callable[..., tuple[OmdbClient, FakeSession]]
    ) -> None:
        # Si el servidor nunca devuelve Response=False y siempre trae resultados,
        # el bucle solo para por OMDB_MAX_SEARCH_PAGES. Sin ese tope, un fallo
        # de la API colgaria la aplicacion.
        from constants import OMDB_MAX_SEARCH_PAGES

        pagina_eterna = {
            "Search": [{"Title": "A", "imdbID": "tt1"}],
            "totalResults": "999999",
            "Response": "True",
        }
        cliente, sesion = omdb_client(FakeResponse(json_data=pagina_eterna))

        resultados = cliente.search_by_actor("Actor")

        assert len(sesion.llamadas) == OMDB_MAX_SEARCH_PAGES
        assert len(resultados) == OMDB_MAX_SEARCH_PAGES


class TestFetchDetail:
    """``fetch_detail``: ``search_by_title`` pero con excepcion."""

    def test_devuelve_el_payload_si_lo_encuentra(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_pelicula_encontrada: dict[str, Any],
    ) -> None:
        cliente, _ = omdb_client(FakeResponse(json_data=omdb_pelicula_encontrada))

        assert cliente.fetch_detail("Interstellar")["Title"] == "Interstellar"

    def test_lanza_movie_not_found_si_no_lo_encuentra(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_pelicula_no_encontrada: dict[str, Any],
    ) -> None:
        cliente, _ = omdb_client(FakeResponse(json_data=omdb_pelicula_no_encontrada))

        with pytest.raises(MovieNotFoundError):
            cliente.fetch_detail("Pelicula Inexistente")

    def test_el_error_conserva_el_titulo_buscado(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_pelicula_no_encontrada: dict[str, Any],
    ) -> None:
        # Lo que hace el mensaje identificable sin tener que parsearlo.
        cliente, _ = omdb_client(FakeResponse(json_data=omdb_pelicula_no_encontrada))

        with pytest.raises(MovieNotFoundError) as exc_info:
            cliente.fetch_detail("Pelicula Inexistente")

        assert exc_info.value.title == "Pelicula Inexistente"
        assert "Pelicula Inexistente" in str(exc_info.value)

    def test_solo_hace_una_peticion(
        self,
        omdb_client: Callable[..., tuple[OmdbClient, FakeSession]],
        omdb_pelicula_encontrada: dict[str, Any],
    ) -> None:
        # `fetch_detail` envuelve a `search_by_title`, no hace su propia peticion.
        cliente, sesion = omdb_client(FakeResponse(json_data=omdb_pelicula_encontrada))

        cliente.fetch_detail("Interstellar")

        assert len(sesion.llamadas) == 1


class TestJerarquiaDelCliente:
    """Propiedades estructurales, no logica."""

    def test_omdb_client_es_un_http_client(self) -> None:
        # De ahi hereda la traduccion de excepciones y el tope de respuesta.
        assert issubclass(OmdbClient, HttpClient)

    def test_es_un_cliente_con_gestor_de_contexto(self) -> None:
        with OmdbClient("https://api.invalid", timeout=1.0, api_key="k") as cliente:
            assert isinstance(cliente, OmdbClient)

    def test_acepta_la_inyeccion_de_sesion(self) -> None:
        # El punto de extension que permite testear sin red. Si alguien lo
        # quitara, toda esta suite dejaria de poder correr sin internet.
        cliente = OmdbClient(
            "https://api.invalid", timeout=1.0, api_key="k", session=FakeSession()
        )

        assert cliente.get_json is not None
