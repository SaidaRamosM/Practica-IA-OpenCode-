"""Clientes de las APIs externas de peliculas y series.

Este paquete aísla por completo el consumo de las APIs: nada fuera de ``api/``
conoce URLs, claves ni el formato de las respuestas crudas.

* :mod:`api.base` — cliente HTTP compartido y validacion del contrato de respuesta.
* :mod:`api.omdb` — peliculas (OMDb).
* :mod:`api.tvmaze` — series (TVMaze).

Los re-exports siguientes son nominales a proposito: el proyecto no usa
wildcard imports.
"""

from api.base import HttpClient
from api.omdb import OmdbClient
from api.tvmaze import TvmazeClient

__all__ = [
    "HttpClient",
    "OmdbClient",
    "TvmazeClient",
]