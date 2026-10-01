"""Error de negocio: la serie solicitada no existe."""

from __future__ import annotations

from exceptions.base import MovieCatalogError


class SeriesNotFoundError(MovieCatalogError):
    """No existe ninguna serie que case con el criterio de busqueda.

    Mismo criterio que :class:`~exceptions.movie_not_found.MovieNotFoundError`:
    :meth:`~services.series_service.SeriesService.search_series` devuelve una
    tupla vacia, y esta clase la lanza
    :meth:`~services.series_service.SeriesService.find_series`.
    """

    def __init__(self, title: str) -> None:
        super().__init__(f"no se encontraron series para {title!r}")
        self.title = title