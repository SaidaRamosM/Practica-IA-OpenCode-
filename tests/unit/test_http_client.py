"""Pruebas de :class:`HttpClient`, la capa que traduce ``requests``.

Aqui viven los escenarios de red: timeout, error de conexion, estados HTTP,
cuerpos que no son JSON y el tope de tamano. Se separan de
``test_omdb.py`` y ``test_tvmaze.py`` a proposito, porque esos comprueban la
logica de cada API --la marca ``Response``, la paginacion, el envoltorio
``show``-- mientras que lo de aqui es comun a las dos.

La traduccion de excepciones es la razon de existir de este modulo: a partir de
este punto, ningun modulo superior puede ver un ``requests.Timeout``.

El doble de la sesion es ``FakeSession``, definida en ``conftest.py``. Se
construye el cliente real y solo se le sustituye la sesion, de modo que se
ejercita el codigo de produccion entero y no una reimplementacion.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from api.base import (
    MAX_RESPONSE_BYTES,
    REDACTED,
    expect_array,
    expect_object,
    redact_query,
    require_text,
)
from exceptions import (
    ApiAuthError,
    ApiConnectionError,
    ApiContractError,
    ApiResponseError,
    ApiTimeoutError,
    EmptyQueryError,
)
from tests.conftest import FAKE_API_KEY
from tests.unit.conftest import FakeResponse, FakeSession


class TestRespuestaCorrecta:
    """El camino feliz: la peticion llega y el JSON se devuelve."""

    def test_devuelve_un_objeto_json_como_mapeo_de_solo_lectura(
        self, http_client: Any
    ) -> None:
        # Arrange
        cliente, _ = http_client(FakeResponse(json_data={"Title": "Interstellar"}))

        # Act
        resultado = cliente.get_json("", {"t": "Interstellar"})

        # Assert
        # MappingProxyType, no dict: la respuesta no se puede mutar por error.
        assert resultado["Title"] == "Interstellar"
        with pytest.raises(TypeError):
            resultado["Title"] = "otro"  # type: ignore[index]

    def test_devuelve_una_lista_json_sin_cambiar_su_tipo(self, http_client: Any) -> None:
        # TVMaze responde con listas en la raiz, y deben llegar como listas.
        cliente, _ = http_client(FakeResponse(json_data=[{"show": {"id": 1}}]))

        resultado = cliente.get_json("/search/shows", {"q": "x"})

        assert isinstance(resultado, list)
        assert resultado[0]["show"]["id"] == 1

    def test_construye_la_url_uniendo_base_y_path(self, http_client: Any) -> None:
        cliente, sesion = http_client(FakeResponse(json_data={}))

        cliente.get_json("/shows/1698")

        assert sesion.llamadas[0]["url"] == "https://api.invalid/shows/1698"

    def test_no_duplica_la_barra_entre_base_y_path(self, http_client: Any) -> None:
        # OMDB_BASE_URL ya acaba en "/" y OMDB_PATH es "": sin el rstrip, la URL
        # saldria con doble barra y el servidor responderia 404.
        cliente, sesion = http_client(FakeResponse(json_data={}), base_url="https://api.invalid/")

        cliente.get_json("/shows")

        assert sesion.llamadas[0]["url"] == "https://api.invalid/shows"

    def test_pasa_el_timeout_configurado(self, http_client: Any) -> None:
        cliente, sesion = http_client(FakeResponse(json_data={}))

        cliente.get_json("", {"t": "x"})

        assert sesion.llamadas[0]["timeout"] == 1.0

    def test_inyecta_la_api_key_como_parametro_apikey(self, http_client: Any) -> None:
        # OMDb la espera con ese nombre exacto en la query.
        cliente, sesion = http_client(FakeResponse(json_data={}))

        cliente.get_json("", {"t": "x"})

        assert sesion.llamadas[0]["params"]["apikey"] == FAKE_API_KEY

    def test_no_inyecta_apikey_si_no_hay_clave_configurada(self, http_client: Any) -> None:
        # TVMaze no lleva clave: mandarla seria ruido, y no tenerla debe funcionar.
        cliente, sesion = http_client(FakeResponse(json_data={}), api_key="")

        cliente.get_json("/search/shows", {"q": "x"})

        assert "apikey" not in sesion.llamadas[0]["params"]

    def test_no_manda_la_peticion_si_no_hay_criterio_de_busqueda(
        self, http_client: Any
    ) -> None:
        # Sin esto, una peticion sin filtros consumiría cuota de la API.
        cliente, sesion = http_client(FakeResponse(json_data={}))

        with pytest.raises(EmptyQueryError):
            cliente.get_json("", {})

        assert sesion.llamadas == []


class TestErroresDeRed:
    """Aqui es donde ``requests`` deja de existir para el resto del proyecto."""

    def test_timeout_se_traduce_a_api_timeout_error(self, http_client: Any) -> None:
        cliente, _ = http_client(error=requests.exceptions.Timeout("tardo demasiado"))

        with pytest.raises(ApiTimeoutError):
            cliente.get_json("", {"t": "x"})

    def test_el_timeout_cita_el_segundo_configurado(self, http_client: Any) -> None:
        cliente, _ = http_client(error=requests.exceptions.Timeout("tarde"))

        with pytest.raises(ApiTimeoutError, match="1.0s"):
            cliente.get_json("", {"t": "x"})

    def test_error_de_conexion_se_traduce_a_api_connection_error(
        self, http_client: Any
    ) -> None:
        cliente, _ = http_client(error=requests.exceptions.ConnectionError("sin red"))

        with pytest.raises(ApiConnectionError):
            cliente.get_json("", {"t": "x"})

    def test_el_error_de_conexion_no_filtra_la_api_key(self, http_client: Any) -> None:
        # El mensaje de requests suele incluir la URL, que lleva la clave.
        cliente, _ = http_client(
            error=requests.exceptions.ConnectionError(f"fallo hacia ?apikey={FAKE_API_KEY}")
        )

        with pytest.raises(ApiConnectionError) as exc_info:
            cliente.get_json("", {"t": "x"})

        assert FAKE_API_KEY not in str(exc_info.value)

    def test_otro_error_de_requests_se_traduce_a_api_response_error(
        self, http_client: Any
    ) -> None:
        cliente, _ = http_client(
            error=requests.exceptions.TooManyRedirects("bucle de redirecciones")
        )

        with pytest.raises(ApiResponseError):
            cliente.get_json("", {"t": "x"})

    def test_timeout_y_conexion_son_irrecuperables_para_reintentar(
        self, http_client: Any
    ) -> None:
        # Son hermanos, no subtipos: el codigo que sepa distinguir "reintentar"
        # de "no reintentar" puede hacerlo por tipo.
        assert not issubclass(ApiTimeoutError, ApiConnectionError)
        assert not issubclass(ApiConnectionError, ApiTimeoutError)

    def test_la_excepcion_original_queda_encadenada_para_poder_depurgar(
        self, http_client: Any
    ) -> None:
        # `from exc` conserva la causa. Es lo que permite ver el traceback real
        # de requests sin que ningun modulo superior tenga que conocerlo.
        cliente, _ = http_client(error=requests.exceptions.Timeout("tarde"))

        with pytest.raises(ApiTimeoutError) as exc_info:
            cliente.get_json("", {"t": "x"})

        assert isinstance(exc_info.value.__cause__, requests.exceptions.Timeout)


class TestErroresHttp:
    """Estados no 2xx, y el caso especial de la credencial rechazada."""

    def test_401_se_traduce_a_api_auth_error(self, http_client: Any) -> None:
        # Es el caso que mas importa: la clave esta mal y reintentar no arregla
        # nada, asi que tiene que ser distinguible de un 500.
        cliente, _ = http_client(
            FakeResponse(status_code=401, text='{"Error":"Invalid API key!"}')
        )

        with pytest.raises(ApiAuthError):
            cliente.get_json("", {"t": "x"})

    def test_403_tambien_es_credencial_rechazada(self, http_client: Any) -> None:
        cliente, _ = http_client(FakeResponse(status_code=403, text="Forbidden"))

        with pytest.raises(ApiAuthError):
            cliente.get_json("", {"t": "x"})

    def test_api_auth_error_conserva_el_codigo_de_estado(self, http_client: Any) -> None:
        cliente, _ = http_client(FakeResponse(status_code=401, text="Unauthorized"))

        with pytest.raises(ApiAuthError) as exc_info:
            cliente.get_json("", {"t": "x"})

        assert exc_info.value.status == 401

    def test_500_se_traduce_a_api_response_error_generico(self, http_client: Any) -> None:
        cliente, _ = http_client(FakeResponse(status_code=500, text="Error del servidor"))

        with pytest.raises(ApiResponseError) as exc_info:
            cliente.get_json("", {"t": "x"})

        # Un 500 no es un problema de credencial: el tipo mas especifico seria
        # equivocado, y ademas sugeriria revisar la clave sin motivo.
        assert not isinstance(exc_info.value, ApiAuthError)

    def test_api_auth_error_es_un_api_response_error(self, http_client: Any) -> None:
        # La jerarquia: el codigo que solo sepa "la API fallo" la sigue
        # capturando sin cambios.
        cliente, _ = http_client(FakeResponse(status_code=401))

        with pytest.raises(ApiResponseError):
            cliente.get_json("", {"t": "x"})

    def test_el_mensaje_incluye_el_cuerpo_del_error(self, http_client: Any) -> None:
        cliente, _ = http_client(
            FakeResponse(status_code=500, text="503 upstream no disponible")
        )

        with pytest.raises(ApiResponseError, match="upstream"):
            cliente.get_json("", {"t": "x"})

    def test_el_mensaje_enmascara_la_clave_reflejada_por_el_servidor(
        self, http_client: Any
    ) -> None:
        # Un servidor puede devolver la clave que recibio en su cuerpo de error.
        cliente, _ = http_client(
            FakeResponse(status_code=500, text=f'{{"error":"apikey {FAKE_API_KEY} invalida"}}')
        )

        with pytest.raises(ApiResponseError) as exc_info:
            cliente.get_json("", {"t": "x"})

        assert FAKE_API_KEY not in str(exc_info.value)
        assert REDACTED in str(exc_info.value)

    def test_la_cadena_de_excepciones_no_filtra_la_clave(self, http_client: Any) -> None:
        # El fallo que motivo la FASE 6: `raise ... from exc` imprime la
        # excepcion original de requests, cuyo mensaje lleva `apikey=` dentro.
        cliente, _ = http_client(FakeResponse(status_code=401, text="Invalid API key!"))

        with pytest.raises(ApiAuthError) as exc_info:
            cliente.get_json("", {"t": "x"})

        cadena = "".join(
            __import__("traceback").format_exception(
                type(exc_info.value), exc_info.value, exc_info.value.__traceback__
            )
        )
        assert FAKE_API_KEY not in cadena
        assert REDACTED in cadena

    def test_trunca_un_cuerpo_de_error_enorme(self, http_client: Any) -> None:
        # Un HTML de error de 50 KB en un mensaje de excepcion no aporta nada.
        cliente, _ = http_client(FakeResponse(status_code=500, text="x" * 50_000))

        with pytest.raises(ApiResponseError) as exc_info:
            cliente.get_json("", {"t": "x"})

        assert len(str(exc_info.value)) < 1_000


class TestCuerpoConFormaInesperada:
    """HTTP 200, pero el cuerpo no sirve."""

    def test_texto_plano_en_vez_de_json_da_api_contract_error(
        self, http_client: Any
    ) -> None:
        # OMDb y TVMaze devuelven HTML ante algunos 4xx, y `json()` falla.
        cliente, _ = http_client(FakeResponse(json_error=ValueError("no es JSON")))

        with pytest.raises(ApiContractError, match="no JSON"):
            cliente.get_json("", {"t": "x"})

    def test_el_error_de_json_menciona_el_content_type(self, http_client: Any) -> None:
        # Ayuda a distinguir "me devolvieron HTML" de "me devolvieron otra cosa".
        cliente, _ = http_client(
            FakeResponse(json_error=ValueError("x"), headers={"Content-Type": "text/html"})
        )

        with pytest.raises(ApiContractError, match="text/html"):
            cliente.get_json("", {"t": "x"})

    def test_un_escalar_json_se_rechaza(self, http_client: Any) -> None:
        # 200 con cuerpo `42` es JSON valido, pero no un objeto ni una lista.
        cliente, _ = http_client(FakeResponse(json_data=42))

        with pytest.raises(ApiContractError, match="int"):
            cliente.get_json("", {"t": "x"})

    def test_una_cadena_json_se_rechaza(self, http_client: Any) -> None:
        cliente, _ = http_client(FakeResponse(json_data="texto"))

        with pytest.raises(ApiContractError):
            cliente.get_json("", {"t": "x"})

    def test_api_contract_error_no_es_error_de_credencial(self, http_client: Any) -> None:
        # El cuerpo raro puede venir de una API que cambio su formato. Tratarlo
        # como problema de clave llevaria a revisar la clave equivocada.
        cliente, _ = http_client(FakeResponse(json_data=42))

        with pytest.raises(ApiContractError) as exc_info:
            cliente.get_json("", {"t": "x"})

        assert not isinstance(exc_info.value, ApiAuthError)


class TestTopeDeTamanoDeRespuesta:
    """Defensa frente a una respuesta anomala que agote la memoria."""

    def test_rechaza_un_content_length_por_encima_del_tope(self, http_client: Any) -> None:
        cliente, _ = http_client(
            FakeResponse(
                json_data={"x": 1},
                headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)},
            )
        )

        with pytest.raises(ApiContractError, match="demasiado grande"):
            cliente.get_json("", {"t": "x"})

    def test_el_error_cita_el_tope_configurado(self, http_client: Any) -> None:
        cliente, _ = http_client(
            FakeResponse(json_data={}, headers={"Content-Length": "9999"}),
            max_response_bytes=1000,
        )

        with pytest.raises(ApiContractError, match="1000"):
            cliente.get_json("", {"t": "x"})

    def test_acepta_una_respuesta_dentro_del_tope(self, http_client: Any) -> None:
        cliente, _ = http_client(
            FakeResponse(json_data={"Title": "x"}, headers={"Content-Length": "500"})
        )

        assert cliente.get_json("", {"t": "x"})["Title"] == "x"

    def test_acepta_una_respuesta_sin_content_length(self, http_client: Any) -> None:
        # No todos los servidores lo envian, y con gzip no refleja el tamano real.
        cliente, _ = http_client(FakeResponse(json_data={"Title": "x"}))

        assert cliente.get_json("", {"t": "x"})["Title"] == "x"

    def test_ignora_un_content_length_no_numerico(self, http_client: Any) -> None:
        # Una cabecera corrupta no puede hacer fallar la consulta.
        cliente, _ = http_client(
            FakeResponse(
                json_data={"Title": "x"},
                headers={"Content-Length": "no-es-un-numero"},
            )
        )

        assert cliente.get_json("/x", {"q": "y"})["Title"] == "x"

    def test_el_tope_por_defecto_es_razonable(self) -> None:
        # 5 MiB: las respuestas reales rondan el kilobyte, asi que el margen es
        # amplio, pero una respuesta anomala no puede agotar el proceso.
        assert MAX_RESPONSE_BYTES == 5 * 1024 * 1024


class TestRedactQuery:
    """``redact_query``: la credencial no llega al log de la peticion."""

    def test_enmascara_el_valor_de_apikey(self) -> None:
        resultado = redact_query({"t": "Matrix", "apikey": "secreta"})

        assert resultado["apikey"] == REDACTED

    @pytest.mark.parametrize(
        "clave",
        ["apikey", "APIKEY", "api_key", "key", "token", "access_token", "password", "secret", "authorization"],
    )
    def test_enmascara_todo_parrafo_sensible_sin_distinguir_mayusculas(
        self, clave: str
    ) -> None:
        assert redact_query({clave: "secreta"})[clave] == REDACTED

    def test_no_toca_los_parametros_normales(self) -> None:
        resultado = redact_query({"t": "Matrix", "page": "2"})

        assert resultado == {"t": "Matrix", "page": "2"}

    def test_no_modifica_el_diccionario_original(self) -> None:
        # Si mutara el original, la peticion real saldria sin credencial.
        original = {"apikey": "secreta", "t": "Matrix"}

        redact_query(original)

        assert original["apikey"] == "secreta"


class TestLogDeDepuracion:
    """Con ``debug=True`` la traza se escribe, y no puede filtrar la clave."""

    def test_la_traza_enmascara_la_credencial(
        self, http_client: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        cliente, _ = http_client(FakeResponse(json_data={}))

        with caplog.at_level(logging.DEBUG, logger="api.base"):
            cliente._debug = True
            cliente.get_json("", {"t": "Matrix"})

        assert FAKE_API_KEY not in caplog.text
        assert REDACTED in caplog.text

    def test_sin_debug_no_se_escribe_la_traza_de_la_peticion(
        self, http_client: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        cliente, _ = http_client(FakeResponse(json_data={}))

        with caplog.at_level(logging.DEBUG, logger="api.base"):
            cliente.get_json("", {"t": "Matrix"})

        assert "params=" not in caplog.text


class TestCicloDeVida:
    """``close()`` solo cierra lo que el cliente creo."""

    def test_crea_su_propia_sesion_cuando_no_se_le_inyecta_ninguna(self) -> None:
        # Sin inyeccion la sesion es suya, y por eso `close()` puede cerrarla.
        # No se comprueba el cierre real: abrir y cerrar un socket aqui violaria
        # la guarda anti-red.
        from api.base import HttpClient

        cliente = HttpClient("https://api.invalid", timeout=1.0, api_key="k")

        assert cliente._owns_session is True
        cliente.close()

    def test_no_cierra_una_sesion_inyectada(self) -> None:
        # La sesion inyectada la posee quien la creo. Cerrarla seria romper al
        # test o a otro cliente que la comparta.
        sesion = FakeSession(FakeResponse(json_data={}))
        from api.base import HttpClient

        cliente = HttpClient("https://api.invalid", timeout=1.0, session=sesion)
        cliente.close()

        assert sesion.cerrada is False

    def test_admite_el_gestor_de_contexto(self) -> None:
        from api.base import HttpClient

        with HttpClient("https://api.invalid", timeout=1.0) as cliente:
            assert cliente.get_json is not None

    def test_el_repr_no_filtra_la_clave(self, http_client: Any) -> None:
        cliente, _ = http_client(FakeResponse(json_data={}))

        assert FAKE_API_KEY not in repr(cliente)


class TestHelpersDeContrato:
    """``expect_object``, ``expect_array`` y ``require_text``."""

    def test_expect_object_acepta_un_mapeo(self) -> None:
        from types import MappingProxyType

        assert expect_object(MappingProxyType({"a": 1}), endpoint="/x", api="API")["a"] == 1

    @pytest.mark.parametrize("payload", [[1, 2], "texto", 42, None])
    def test_expect_object_rechaza_lo_que_no_es_objeto(self, payload: Any) -> None:
        with pytest.raises(ApiContractError, match="se esperaba un objeto"):
            expect_object(payload, endpoint="/x", api="API")

    def test_expect_array_acepta_una_lista(self) -> None:
        assert expect_array([{"a": 1}], endpoint="/x", api="API")[0]["a"] == 1

    @pytest.mark.parametrize("payload", [{"a": 1}, "texto", 42, None])
    def test_expect_array_rechaza_lo_que_no_es_lista(self, payload: Any) -> None:
        with pytest.raises(ApiContractError, match="se esperaba una lista"):
            expect_array(payload, endpoint="/x", api="API")

    def test_un_mapeado_de_solo_lectura_no_pasa_por_expect_array(self) -> None:
        # `get_json` devuelve `MappingProxyType` para los dict, asi que es justo
        # el tipo que llega aqui cuando se espera una lista. El error tiene que
        # decir "dict" y no "mappingproxy": el envoltorio es un detalle interno
        # de inmutabilidad y en un mensaje solo confunde.
        from types import MappingProxyType

        with pytest.raises(ApiContractError, match="devolvio dict"):
            expect_array(MappingProxyType({"a": 1}), endpoint="/x", api="API")

    def test_expect_object_acepta_un_mapeado_de_solo_lectura(self) -> None:
        from types import MappingProxyType

        assert expect_object(MappingProxyType({"a": 1}), endpoint="/x", api="API") == {"a": 1}

    def test_require_text_recorta_y_devuelve(self) -> None:
        assert require_text("  Matrix  ", "titulo") == "Matrix"

    @pytest.mark.parametrize("valor", ["", "   "])
    def test_require_text_rechaza_lo_vacio(self, valor: str) -> None:
        with pytest.raises(EmptyQueryError, match="titulo"):
            require_text(valor, "titulo")

    def test_require_text_impide_manipular_la_url_con_ampersand(self) -> None:
        # Sin esta comprobacion, "Matrix &t=Rocky" habria anadido un criterio
        # falso a la peticion. Que lo acepte es correcto: el problema era
        # concatenar en la URL, y eso ya no ocurre.
        assert require_text("Matrix &t=Rocky", "titulo") == "Matrix &t=Rocky"
