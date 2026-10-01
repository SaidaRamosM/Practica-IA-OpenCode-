"""Logica de negocio de peliculas.

Coordina a :mod:`api.omdb` y el catalogo local, y devuelve objetos
:class:`~models.movie.Movie` en lugar de diccionarios crudos.

No contiene ``print()`` ni ``input()``: presentar es trabajo de :mod:`ui`.
"""

from __future__ import annotations

import logging
from typing import Any

from api.base import HttpClient, require_text
from api.omdb import OmdbClient
from cache import TTLCache
from config import AppConfig
from constants import (
    GENRE_LABELS,
    MOVIES_BY_GENRE,
    OMDB_BASE_URL,
    POPULAR_MOVIES,
    LocalMovie,
)
from exceptions import MovieNotFoundError
from models.movie import Movie

logger = logging.getLogger(__name__)


class MovieService:
    """Catalogo de peliculas: remotas (OMDb) y local (semilla estatica).

    Es dueño de su cliente de OMDb y de sus dos caches (la de busquedas y la
    del catalogo local), de forma que :class:`~services.series_service.SeriesService`
    y este no comparten estado.
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        omdb: HttpClient | None = None,
    ) -> None:
        self._config = config
        self._omdb = omdb if omdb is not None else OmdbClient(
            OMDB_BASE_URL,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            api_key=config.omdb_api_key,
            debug=config.debug,
        )
        self._movie_cache: TTLCache[Movie] = TTLCache(
            config.cache_ttl_seconds, max_entries=config.cache_max_entries
        )
        self._local_cache: TTLCache[Any] = TTLCache(
            config.cache_ttl_seconds, max_entries=config.cache_max_entries
        )

    # -- busquedas remotas --------------------------------------------------
    def search_movie(self, title: str) -> Movie | None:
        """Busca una pelicula por titulo, con cache.

        :returns: la pelicula, o ``None`` si no existe.
        """
        query = require_text(title, "titulo")
        cache_key = f"movie:{query.casefold()}"
        cached = self._movie_cache.get(cache_key)
        if cached is not None:
            logger.debug("cache HIT %s", cache_key)
            return cached

        payload = self._omdb.search_by_title(query)
        # Solo se cachea un acierto: antes se cacheaban tambien los fallos.
        if payload is None:
            logger.info("pelicula no encontrada en OMDb: %s", query)
            return None
        movie = Movie.from_payload(payload)
        logger.info("pelicula encontrada en OMDb: %s (%s)", movie.title, movie.year)
        self._movie_cache.set(cache_key, movie)
        return movie

    def fetch_movie(self, title: str) -> Movie:
        """Como :meth:`search_movie`, pero lanza excepcion si no encuentra.

        :raises MovieNotFoundError: si no hay resultados.
        """
        movie = self.search_movie(title)
        if movie is None:
            raise MovieNotFoundError(title)
        return movie

    def movies_by_actor(self, actor: str) -> tuple[Movie, ...]:
        """Peliculas de un actor, paginadas y cacheadas."""
        query = require_text(actor, "actor")
        cache_key = f"actor:{query.casefold()}"
        cached = self._movie_cache.get(cache_key)
        if cached is not None:
            logger.debug("cache HIT %s", cache_key)
            return tuple(cached)

        movies = tuple(Movie.from_payload(p) for p in self._omdb.search_by_actor(query))
        if movies:
            logger.info("%d peliculas encontradas en OMDb para el actor %s", len(movies), query)
            self._movie_cache.set(cache_key, movies)
        return movies

    # -- catalogo local (sin red) -------------------------------------------
    def popular_movies(self) -> tuple[LocalMovie, ...]:
        """Peliculas populares del catalogo local. No hace ninguna peticion."""
        cached = self._local_cache.get("local:popular")
        if cached is not None:
            return tuple(cached)
        self._local_cache.set("local:popular", POPULAR_MOVIES)
        return POPULAR_MOVIES

    def movies_by_genre(self, genre: str) -> tuple[LocalMovie, ...]:
        """Peliculas del catalogo local para *genre*.

        Un genero desconocido devuelve el catalogo completo, que era el
        comportamiento del ``if/elif/else`` original.
        """
        key = genre.strip().casefold()
        cache_key = f"local:genre:{key}"
        cached = self._local_cache.get(cache_key)
        if cached is not None:
            return tuple(cached)

        selected = MOVIES_BY_GENRE.get(key, _all_local_movies())
        self._local_cache.set(cache_key, selected)
        return selected

    @staticmethod
    def available_genres() -> tuple[str, ...]:
        """Generos disponibles en el catalogo local."""
        return GENRE_LABELS

    # -- diagnostico ---------------------------------------------------------
    def movie_cache_stats(self) -> dict[str, float | int]:
        """Metricas de la cache de busquedas de peliculas."""
        return self._movie_cache.stats().as_dict()

    def local_cache_stats(self) -> dict[str, float | int]:
        """Metricas de la cache del catalogo local."""
        return self._local_cache.stats().as_dict()

    def clear_caches(self) -> None:
        """Vacia ambas caches. Las metricas se conservan."""
        self._movie_cache.clear()
        self._local_cache.clear()

    @property
    def config(self) -> AppConfig:
        return self._config

    def close(self) -> None:
        """Libera la conexion HTTP del cliente que se creo aqui."""
        self.clear_caches()
        if isinstance(self._omdb, HttpClient):
            self._omdb.close()

    def __enter__(self) -> MovieService:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"MovieService(timeout={self._config.request_timeout!r})"


def _all_local_movies() -> tuple[LocalMovie, ...]:
    """Catalogo local completo, sin duplicar la constante."""
    return tuple(movie for movies in MOVIES_BY_GENRE.values() for movie in movies) + POPULAR_MOVIES


__all__ = ["MovieService"]