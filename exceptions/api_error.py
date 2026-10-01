"""Errores de comunicacion con las APIs externas.

La capa :mod:`api` es la unica que traduce las excepciones de ``requests`` a
estas clases, de modo que ningun modulo superior tiene que conocer la libreria
de red.

Jerarquia:

.. code-block:: text

    ApiError
     +-- ApiTimeoutError      se agoto el timeout
     +-- ApiConnectionError    no se pudo conectar
     +-- ApiResponseError      estado HTTP no 2xx
          +-- ApiAuthError     401/403: credencial rechazada
          +-- ApiContractError  la respuesta no cumple el contrato
"""

from __future__ import annotations

from exceptions.base import MovieCatalogError


class ApiError(MovieCatalogError):
    """Fallo al comunicarse con una API externa."""

    def __init__(self, message: str, *, endpoint: str | None = None) -> None:
        super().__init__(message)
        self.endpoint = endpoint

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base} (endpoint={self.endpoint})" if self.endpoint else base


class ApiTimeoutError(ApiError):
    """La API no respondio dentro del timeout configurado."""


class ApiConnectionError(ApiError):
    """No se pudo establecer conexion con la API."""


class ApiResponseError(ApiError):
    """La API respondio, pero con un estado HTTP no exitoso."""


class ApiAuthError(ApiResponseError):
    """La API rechazo la credencial (HTTP 401 o 403).

    Se separa de :class:`ApiResponseError` porque la accion que debe tomar el
    usuario es distinta: revisar ``OMDB_API_KEY`` en lugar de reintentar. Hereda
    de ``ApiResponseError``, de modo que el codigo que solo sepa de "la API
    fallo" sigue capturandola sin cambios.
    """

    def __init__(self, message: str, *, endpoint: str | None = None, status: int | None = None) -> None:
        super().__init__(message, endpoint=endpoint)
        self.status = status

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base} (status={self.status})" if self.status else base


class ApiContractError(ApiResponseError):
    """La API respondio 200 pero el cuerpo no tiene la forma esperada."""