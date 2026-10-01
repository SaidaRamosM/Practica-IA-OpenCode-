"""Base compartida por los clientes HTTP de las APIs externas.

Este modulo no pertenece a ninguna API en concreto: contiene lo que ``api/omdb.py``
y ``api/tvmaze.py`` necesitan por igual.

* :class:`HttpClient` envuelve :class:`requests.Session` y traduce las
  excepciones de la libreria de red a las de :mod:`exceptions`, de modo que
  ningun modulo superior tenga que conocer ``requests``.
* ``_expect_object`` y ``_expect_array`` validan la forma de la respuesta, que
  no es homogenea entre APIs: OMDb responde con objetos y TVMaze con listas en la
  raiz.
* :func:`require_text` normaliza un criterio de busqueda antes de construir la
  peticion.

Se separo de los clientes especificos en la FASE 3 para no duplicar estas ~120
lineas en dos ficheros, que es lo que habria ocurrido de mantenerlo todo en un
unico ``api_movies.py``.
"""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping

import requests

from constants import HTTP_ERROR_DETAIL_MAX_LENGTH
from exceptions import (
    ApiAuthError,
    ApiConnectionError,
    ApiContractError,
    ApiResponseError,
    ApiTimeoutError,
    EmptyQueryError,
)

logger = logging.getLogger(__name__)

#: Respuesta JSON de una API externa. No es homogenea entre APIs: OMDb responde
#: con objetos y TVMaze con listas en la raiz.
JsonObject = Mapping[str, Any]
JsonArray = list[Any]
JsonValue = JsonObject | JsonArray

#: Marcador que sustituye a un valor sensible en las trazas.
REDACTED: Final[str] = "***"

#: Parametros de consulta cuyo valor nunca debe quedar en un log. La clave de
#: OMDb viaja como parametro de query, de modo que registrar el diccionario
#: completo la escribiria en texto plano en cuanto ``APP_DEBUG`` estuviera
#: activo. Se compares el nombre sin distinguir mayusculas.
SENSITIVE_QUERY_KEYS: Final[frozenset[str]] = frozenset({
    "apikey",
    "api_key",
    "key",
    "token",
    "access_token",
    "password",
    "secret",
    "authorization",
})


#: Estados HTTP que indican credencial rechazada. Se traducen a
#: :class:`~exceptions.api_error.ApiAuthError` en vez de
#: :class:`~exceptions.api_error.ApiResponseError`.
AUTH_ERROR_STATUSES: Final[frozenset[int]] = frozenset({401, 403})

#: Tope por defecto del cuerpo de una respuesta. Las respuestas de OMDb y
#: TVMaze para las consultas de este proyecto rondan el kilobyte; 5 MiB es un
#: margen amplisimo que aun asi impide que una respuesta anomala agote la
#: memoria del proceso.
MAX_RESPONSE_BYTES: Final[int] = 5 * 1024 * 1024


def redact_query(query: Mapping[str, Any]) -> dict[str, Any]:
    """Devuelve una copia de *query* con enmascarados los valores sensibles.

    Solo afecta a lo que se registra: la peticion real sigue enviando el valor
    original a la API.

    >>> redact_query({"t": "Matrix", "apikey": "secreta"})
    {'t': 'Matrix', 'apikey': '***'}
    >>> redact_query({"apikey": "secreta"})["apikey"] == "secreta"
    False
    """
    return {
        key: (REDACTED if str(key).casefold() in SENSITIVE_QUERY_KEYS else value)
        for key, value in query.items()
    }


def _json_type_name(payload: Any) -> str:
    """Nombre legible del tipo, sin exponer detalles internos.

    ``MappingProxyType`` se reporta como ``dict``: es un envoltorio de
    inmutabilidad interno y en un mensaje de error solo confunde.
    """
    if isinstance(payload, MappingProxyType):
        return "dict"
    return type(payload).__name__


def expect_object(payload: JsonValue, *, endpoint: str, api: str) -> JsonObject:
    """Valida que la respuesta sea un objeto JSON.

    :raises ApiContractError: si es una lista u otro tipo.
    """
    if not isinstance(payload, Mapping):
        raise ApiContractError(
            f"{api} devolvio {_json_type_name(payload)} en {endpoint}; se esperaba un objeto",
            endpoint=endpoint,
        )
    return payload


def expect_array(payload: JsonValue, *, endpoint: str, api: str) -> JsonArray:
    """Valida que la respuesta sea una lista JSON.

    :raises ApiContractError: si es un objeto u otro tipo.
    """
    if not isinstance(payload, list):
        raise ApiContractError(
            f"{api} devolvio {_json_type_name(payload)} en {endpoint}; se esperaba una lista",
            endpoint=endpoint,
        )
    return payload


def require_text(value: str, field: str) -> str:
    """Valida y normaliza un criterio de busqueda.

    Antes la consulta se concatenaba directamente en la URL, de modo que un
    titulo con ``&`` manipulaba los parametros de la peticion.

    :raises EmptyQueryError: si *value* esta en blanco.
    """
    text = value.strip()
    if not text:
        raise EmptyQueryError(f"el campo '{field}' no puede estar vacio")
    return text


def _sanitize_exception(exc: BaseException, redact: Callable[[str], str]) -> BaseException:
    """Reescribe ``exc.args`` con el texto saneado y devuelve la excepcion.

    ``raise ... from exc`` imprime la cadena completa de excepciones, incluida
    la original de ``requests``, cuyo mensaje contiene la URL efectiva **con
    ``apikey=...`` dentro**. Sin este paso, un ``logger.exception`` basta para
    escribir la credencial en el log. Se conservan tipo y traceback: solo
    cambia el texto.
    """
    try:
        exc.args = tuple(
            redact(a) if isinstance(a, str) else a for a in exc.args
        )
    except (AttributeError, TypeError, ValueError):
        # Una excepcion con args de solo lectura no se puede reescribir. No es
        # motivo para propagar un fallo aqui: el mensaje propio que se va a
        # lanzar ya viene saneado, y la original solo se usa como causa.
        logger.debug("no se pudo sanear la excepcion original", exc_info=True)
    return exc


def _content_length(response: Any) -> int | None:
    """Tamano declarado del cuerpo, o ``None`` si no se puede saber.

    Se leen ``Content-Length`` y, cuando viene comprimido, ``Content-Length``
    no refleja el tamano descomprimido, por eso solo se usa como filtro
    temprano y no como garantia.
    """
    raw = response.headers.get("Content-Length") if hasattr(response, "headers") else None
    if raw is None:
        return None
    try:
        valor = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return valor if valor >= 0 else None


class HttpClient:
    """Cliente HTTP minimo sobre :class:`requests.Session`."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        max_retries: int = 0,
        api_key: str | None = None,
        debug: bool = False,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._api_key = api_key
        self._debug = debug
        self._max_response_bytes = max_response_bytes
        # Se acepta una Session por inyeccion para poder testear sin red.
        self._session = session if session is not None else requests.Session()
        self._owns_session = session is None
        self._adapter = requests.adapters.HTTPAdapter(max_retries=max_retries)
        self._session.mount("https://", self._adapter)
        self._session.mount("http://", self._adapter)

    def get_json(
        self,
        path: str,
        params: Mapping[str, str] | None = None,
    ) -> JsonValue:
        """GET a ``base_url + path`` y devuelve el JSON ya decodificado.

        Acepta tanto un objeto como una lista; la forma concreta se valida en el
        metodo que llama, con :func:`expect_object` o :func:`expect_array`.

        :raises EmptyQueryError: si *params* es un mapeo vacio.
        :raises ApiTimeoutError: si se agota el timeout.
        :raises ApiConnectionError: si no hay conexion.
        :raises ApiResponseError: si el estado HTTP no es 2xx.
        :raises ApiContractError: si el cuerpo no es JSON de objeto ni de lista.
        """
        if params is not None and not params:
            raise EmptyQueryError("la peticion no incluye ningun criterio de busqueda")

        url = f"{self._base_url.rstrip('/')}{path}"
        query: dict[str, str] = dict(params or {})
        if self._api_key:
            query["apikey"] = self._api_key

        if self._debug:
            # Se enmascara la clave: registrarla en claro convertiria el log en
            # un archivo de credenciales.
            logger.debug(
                "GET %s params=%s timeout=%s", url, redact_query(query), self._timeout
            )

        try:
            response = self._session.get(url, params=query, timeout=self._timeout)
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise ApiTimeoutError(
                f"timeout de {self._timeout}s esperando a {self._base_url}", endpoint=url
            ) from _sanitize_exception(exc, self._redact)
        except requests.exceptions.ConnectionError as exc:
            raise ApiConnectionError(
                f"no se pudo conectar con {self._base_url}", endpoint=url
            ) from _sanitize_exception(exc, self._redact)
        except requests.exceptions.HTTPError as exc:
            # El mensaje de requests incluye la URL efectiva, que lleva
            # `apikey` dentro. Se sanea el cuerpo y la excepcion original
            # antes de construir el mensaje propio.
            status = getattr(exc.response, "status_code", None)
            detail = getattr(exc.response, "text", "") or ""
            detail = self._redact(detail[:HTTP_ERROR_DETAIL_MAX_LENGTH])
            _sanitize_exception(exc, self._redact)
            message = f"estado HTTP {status} en {url}: {detail}"
            # 401/403 no son un fallo transitorio: reintentar no arregla una
            # credencial invalida. Se distinguen para que la interfaz pueda
            # sugerir revisar la clave en vez de invite a reintentar.
            if status in AUTH_ERROR_STATUSES:
                raise ApiAuthError(message, endpoint=url, status=status) from exc
            raise ApiResponseError(message, endpoint=url) from exc
        except requests.exceptions.RequestException as exc:
            raise ApiResponseError(
                f"fallo de red en {url}: {self._redact(str(exc))}", endpoint=url
            ) from _sanitize_exception(exc, self._redact)

        # Tope de seguridad: un servidor comprometido o un intermediario podria
        # enviar un cuerpo enorme y agotar la memoria. Se comprueba la cabecera
        # antes de descargar, y luego el tamano real ya leido.
        declared = _content_length(response)
        if declared is not None and declared > self._max_response_bytes:
            raise ApiContractError(
                f"respuesta demasiado grande desde {url}: "
                f"{declared} bytes declarados, maximo {self._max_response_bytes}",
                endpoint=url,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            # OMDb y TVMaze devuelven HTML o texto plano ante algunos 4xx.
            content_type = response.headers.get("Content-Type", "?")
            raise ApiContractError(
                f"cuerpo no JSON desde {url} (Content-Type={content_type})",
                endpoint=url,
            ) from exc

        actual = _content_length(response)
        if actual is not None and actual > self._max_response_bytes:
            raise ApiContractError(
                f"respuesta demasiado grande desde {url}: "
                f"{actual} bytes recibidos, maximo {self._max_response_bytes}",
                endpoint=url,
            )

        if not isinstance(payload, (dict, list)):
            raise ApiContractError(
                f"se esperaba un objeto o una lista JSON desde {url}, "
                f"se recibio {type(payload).__name__}",
                endpoint=url,
            )

        logger.debug("respuesta OK desde %s", url)
        return MappingProxyType(payload) if isinstance(payload, dict) else payload

    def _redact(self, text: str) -> str:
        """Sustituye la API key por :data:`REDACTED` dentro de *text*.

        Se aplica a todo texto que venga del servidor o de ``requests`` antes
        de guardarlo en un mensaje de excepcion o en el log.
        """
        if not text or not self._api_key:
            return text
        return text.replace(self._api_key, REDACTED)

    def close(self) -> None:
        """Cierra la sesion, pero solo si este cliente la creo."""
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self._base_url!r}, timeout={self._timeout!r})"