"""Utilidades de los tests unitarios: guarda anti-red y dobles de ``requests``.

Lo importante de este modulo es ``no_network``. Sin ella, "test unitario" es
una promesa en un comentario; con ella, es una propiedad verificada.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import requests

from api.base import HttpClient
from api.omdb import OmdbClient
from api.tvmaze import TvmazeClient
from constants import OMDB_BASE_URL, TVMAZE_BASE_URL
from tests.conftest import FAKE_API_KEY


# ---------------------------------------------------------------------------
# La regla: test unitario = sin internet
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hace fallar cualquier test unitario que intente abrir un socket.

    Es ``autouse``, asi que no hay que recordarlo. Sustituye ``socket.socket`` por
    una version que lanza en ``connect``, que es el punto por el que salen las
    peticiones reales tanto de ``requests`` como de ``urllib3``.

    Que falle y no que se salte es deliberado: un test unitario que depende de
    la red no es lento, es incorrecto, y conviene enterarse al escribirlo y no
    tres meses despues.
    """

    def _conectar(self: Any, address: Any) -> Any:
        raise AssertionError(
            f"un test unitario intento abrir un socket hacia {address!r}. "
            "Simula la sesion de requests en vez de llamar a la red real."
        )

    monkeypatch.setattr(socket.socket, "connect", _conectar)
    monkeypatch.setattr(
        socket.socket,
        "connect_ex",
        lambda self, address: _conectar(self, address),
    )


# ---------------------------------------------------------------------------
# Dobles de la sesion de requests
# ---------------------------------------------------------------------------
class FakeResponse:
    """Respuesta HTTP simulada con la superficie que usa :class:`HttpClient`.

    No es un ``Mock`` generico a proposito: los atributos estan declarados, de
    modo que si ``HttpClient`` empieza a leer uno nuevo, este doble se queda
    corto y el test falla diciendo exactamente cual falta, en vez de devolver un
    ``Mock`` que acepta cualquier cosa y esconde el problema.
    """

    def __init__(
        self,
        *,
        status_code: int = 200,
        json_data: Any = None,
        text: str = "",
        headers: dict[str, str] | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.text = text
        self._json_data = {} if json_data is None else json_data
        self._json_error = json_error

    def raise_for_status(self) -> None:
        """Reproduce ``requests.Response.raise_for_status`` sin el HTTP real.

        Lanza la excepcion que ``requests`` lanzaria, que es justo lo que
        ``HttpClient`` traduce a su propia jerarquia.
        """
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Client Error: for url: "
                f"https://api.invalid/?apikey={FAKE_API_KEY}",
                response=self,  # type: ignore[arg-type]
            )

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


class FakeSession:
    """Sesion de ``requests`` simulada.

    Recibe la respuesta a devolver, o una excepcion a lanzar, o una funcion que
    decide la respuesta segun la peticion.     Se registran las llamadas en
    ``llamadas`` para poder comprobar que se construyó la URL y los parámetros
    correctos, que es parte del comportamiento de ``HttpClient``.
    """

    def __init__(
        self,
        response: FakeResponse | None = None,
        *,
        error: Exception | None = None,
        handler: Callable[[str, dict[str, str]], Any] | None = None,
    ) -> None:
        self._response = response if response is not None else FakeResponse()
        self._error = error
        self._handler = handler
        self.llamadas: list[dict[str, Any]] = []
        self.montados: list[str] = []
        self.cerrada = False

    def get(
        self, url: str, *, params: dict[str, str] | None = None, timeout: Any = None
    ) -> Any:
            # `params` se copia porque el cliente lo puede mutar (añade `apikey`):
        # guardar la referencia haria que la asercion viera el dict ya cambiado.
        self.llamadas.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        if self._error is not None:
            raise self._error
        if self._handler is not None:
            return self._handler(url, dict(params or {}))
        return self._response

    def mount(self, prefix: str, adapter: Any) -> None:
        self.montados.append(prefix)

    def close(self) -> None:
        self.cerrada = True


@pytest.fixture
def fake_session() -> Callable[..., FakeSession]:
    """Fabrica de :class:`FakeSession`.

    Se devuelve la clase en vez de una instancia porque cada test necesita la
    suya: compartirla haria que un test viera las llamadas de otro.
    """
    return FakeSession


# ---------------------------------------------------------------------------
# Clientes reales con la sesion simulada
#
# Se construye el cliente de verdad y solo se le cambia la sesion. Asi los tests
# de `api/` ejercitan el codigo de produccion completo -- validacion de
# contrato, traduccion de excepciones, paginacion -- y no una reimplementacion.
# ---------------------------------------------------------------------------
@pytest.fixture
def http_client() -> Callable[..., tuple[HttpClient, FakeSession]]:
    """``(cliente, sesion)`` de un ``HttpClient`` que no sale a la red."""

    def _crear(
        response: FakeResponse | None = None,
        *,
        error: Exception | None = None,
        handler: Callable[[str, dict[str, str]], Any] | None = None,
        api_key: str = FAKE_API_KEY,
        base_url: str = "https://api.invalid",
        max_response_bytes: int | None = None,
    ) -> tuple[HttpClient, FakeSession]:
        kwargs: dict[str, Any] = {"max_response_bytes": max_response_bytes} if max_response_bytes else {}
        sesion = FakeSession(response, error=error, handler=handler)
        cliente = HttpClient(
            base_url,
            timeout=1.0,
            api_key=api_key,
            session=sesion,
            **kwargs,
        )
        return cliente, sesion

    return _crear


@pytest.fixture
def omdb_client() -> Callable[..., tuple[OmdbClient, FakeSession]]:
    """``(cliente, sesion)`` de un :class:`OmdbClient` que no sale a la red."""

    def _crear(
        response: FakeResponse | None = None,
        *,
        error: Exception | None = None,
        handler: Callable[[str, dict[str, str]], Any] | None = None,
        api_key: str = FAKE_API_KEY,
    ) -> tuple[OmdbClient, FakeSession]:
        sesion = FakeSession(response, error=error, handler=handler)
        cliente = OmdbClient(
            OMDB_BASE_URL, timeout=1.0, api_key=api_key, session=sesion
        )
        return cliente, sesion

    return _crear


@pytest.fixture
def tvmaze_client() -> Callable[..., tuple[TvmazeClient, FakeSession]]:
    """``(cliente, sesion)`` de un :class:`TvmazeClient` que no sale a la red.

    TVMaze es publica, asi que se deja la clave a ``None`` como en produccion.
    """

    def _crear(
        response: FakeResponse | None = None,
        *,
        error: Exception | None = None,
        handler: Callable[[str, dict[str, str]], Any] | None = None,
    ) -> tuple[TvmazeClient, FakeSession]:
        sesion = FakeSession(response, error=error, handler=handler)
        cliente = TvmazeClient(TVMAZE_BASE_URL, timeout=1.0, session=sesion)
        return cliente, sesion

    return _crear


# ---------------------------------------------------------------------------
# Dobles de los clientes de API para los servicios
# ---------------------------------------------------------------------------
@pytest.fixture
def omdb_mock() -> Any:
    """Cliente de OMDb simulado, para inyectar en :class:`MovieService`.

    Un ``Mock`` es lo que pide la instruccion de la fase, y aqui es lo
    adecuado: ``MovieService`` solo usa el protocolo de ``HttpClient``
    (``search_by_title``, ``search_by_actor``), asi que un doble por metodo
    basta. Lo que si importa es que ``close`` exista, porque el servicio la
    llama en su ``close``.
    """
    from unittest.mock import Mock

    cliente = Mock(name="OmdbClient")
    cliente.close.return_value = None
    return cliente


@pytest.fixture
def tvmaze_mock() -> Any:
    """Cliente de TVMaze simulado, para inyectar en :class:`SeriesService`."""
    from unittest.mock import Mock

    cliente = Mock(name="TvmazeClient")
    cliente.close.return_value = None
    return cliente


@pytest.fixture
def reloj_falso() -> Iterator[Callable[[], float]]:
    """Reloj controlable para :class:`TTLCache`.

    Devuelve una funcion con ``.avanza(segundos)``, de modo que los tests de
    caducidad no dependen de ``time.sleep`` ni de parches de ``monotonic``.
    """
    instante = {"actual": 1000.0}

    def reloj() -> float:
        return instante["actual"]

    def avanza(segundos: float) -> None:
        instante["actual"] += segundos

    reloj.avanza = avanza  # type: ignore[attr-defined]
    yield reloj  # type: ignore[misc]
