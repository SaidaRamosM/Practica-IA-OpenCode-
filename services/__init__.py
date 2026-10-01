"""Capa de servicios: logica de negocio por dominio.

Cada servicio coordina un cliente de :mod:`api`, aplica la cache y devuelve
objetos de :mod:`models`. Ningun servicio imprime ni lee de la entrada
estandar: la interaccion es de :mod:`ui`.

* :mod:`services.movie_service` — peliculas (OMDb y catalogo local)
* :mod:`services.series_service` — series (TVMaze)
"""

from services.movie_service import MovieService
from services.series_service import SeriesService

__all__ = [
    "MovieService",
    "SeriesService",
]