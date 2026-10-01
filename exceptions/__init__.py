"""Jerarquia de excepciones del dominio.

Este paquete reexporta los mismos nombres que el antiguo modulo suelto
``exceptions.py``. Como ``__init__`` los expone a traves de ``__all__``, los
ocho sitios que hacian ``from exceptions import (...)`` del proyecto siguen
funcionando sin tocar una sola linea: la conversion a paquete no cambio la
interfaz publica.

.. code-block:: text

    MovieCatalogError                    (exceptions.base)
     +-- ApiError                        (exceptions.api_error)
     |    +-- ApiTimeoutError
     |    +-- ApiConnectionError
     |    +-- ApiResponseError
     |         +-- ApiAuthError          401/403
     |         +-- ApiContractError     cuerpo con forma inesperada
     +-- MovieNotFoundError              (exceptions.movie_not_found)
     +-- SeriesNotFoundError             (exceptions.series_not_found)
     +-- ConfigError                     (exceptions.configuration_error)
     |                                     tambien hereda de ValueError
     +-- StorageError                    (exceptions.storage_error)
     |    +-- CorruptedStorageError
     +-- EmptyQueryError                 (exceptions.user_input_error)
     +-- UserCancelledError              (exceptions.user_input_error)
"""

from exceptions.api_error import (
    ApiAuthError,
    ApiConnectionError,
    ApiContractError,
    ApiError,
    ApiResponseError,
    ApiTimeoutError,
)
from exceptions.base import MovieCatalogError
from exceptions.configuration_error import ConfigError
from exceptions.movie_not_found import MovieNotFoundError
from exceptions.series_not_found import SeriesNotFoundError
from exceptions.storage_error import CorruptedStorageError, StorageError
from exceptions.user_input_error import EmptyQueryError, UserCancelledError

__all__ = [
    # base
    "MovieCatalogError",
    # api
    "ApiError",
    "ApiTimeoutError",
    "ApiConnectionError",
    "ApiResponseError",
    "ApiAuthError",
    "ApiContractError",
    # negocio
    "MovieNotFoundError",
    "SeriesNotFoundError",
    # configuracion
    "ConfigError",
    # persistencia
    "StorageError",
    "CorruptedStorageError",
    # interaccion
    "EmptyQueryError",
    "UserCancelledError",
]