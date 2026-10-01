"""Error de negocio: la pelicula solicitada no existe."""

from __future__ import annotations

from exceptions.base import MovieCatalogError


class MovieNotFoundError(MovieCatalogError):
    """No existe ninguna pelicula que case con el criterio de busqueda.

    Nota de uso: :meth:`~services.movie_service.MovieService.search_movie`
    devuelve ``None`` en este caso, porque la interfaz necesita distinguir
    "no encontrado" de "error de red" sin capturar excepcion. Esta clase la
    lanza :meth:`~services.movie_service.MovieService.fetch_movie`, para el
    llamador que prefiera el fallo explicito.
    """

    def __init__(self, title: str) -> None:
        super().__init__(f"no se encontro la pelicula {title!r}")
        self.title = title