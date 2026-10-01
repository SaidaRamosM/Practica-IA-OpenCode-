"""Logica de negocio de series.

Coordina a :mod:`api.tvmaze` y devuelve objetos
:class:`~models.series.Series` en lugar de diccionarios crudos.

No contiene ``print()`` ni ``input()``: presentar es trabajo de :mod:`ui`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from api.base import HttpClient, JsonObject, require_text
from api.tvmaze import TvmazeClient
from cache import TTLCache
from config import AppConfig
from constants import (
    TVMAZE_BASE_URL,
    TVMAZE_SHOW_ID_KEY,
    TVMAZE_SHOW_KEY,
)
from exceptions import ApiContractError, EmptyQueryError, SeriesNotFoundError
from models.series import Series

logger = logging.getLogger(__name__)


class SeriesService:
    """Catalogo de series via TVMaze.

    Es dueño de su cliente y de su cache, de forma que no comparte estado con
    :class:`~services.movie_service.MovieService`.
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        tvmaze: HttpClient | None = None,
    ) -> None:
        self._config = config
        self._tvmaze = tvmaze if tvmaze is not None else TvmazeClient(
            TVMAZE_BASE_URL,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            debug=config.debug,
        )
        self._series_cache: TTLCache[Any] = TTLCache(
            config.cache_ttl_seconds, max_entries=config.cache_max_entries
        )

    # -- busquedas ----------------------------------------------------------
    def _search_payloads(self, name: str) -> tuple[JsonObject, ...]:
        """Envoltorios crudos de la busqueda, cacheados.

        Privado porque :meth:`find_series` necesita distinguir un envoltorio
        ``{"show": {...}}`` de un objeto plano, y esa distincion se pierde en
        cuanto :class:`Series` normaliza el payload.
        """
        query = require_text(name, "nombre de serie")
        cache_key = f"series:{query.casefold()}"
        cached = self._series_cache.get(cache_key)
        if cached is not None:
            logger.debug("cache HIT %s", cache_key)
            return tuple(cached)

        shows = self._tvmaze.search_shows(query)
        if shows:
            logger.info("%d series encontradas en TVMaze para %s", len(shows), query)
            self._series_cache.set(cache_key, shows)
        return shows

    def search_series(self, name: str) -> tuple[Series, ...]:
        """Series que casan con *name*, cacheadas.

        Cada resultado se normaliza con :meth:`Series.from_payload`, que
        desenvuelve ``{"show": {...}}``.
        """
        return tuple(Series.from_payload(p) for p in self._search_payloads(name))

    def series_details(self, show_id: int | str) -> Series:
        """Detalle de una serie, cacheado por id."""
        raw = str(show_id).strip()
        if not raw or raw == "None":
            raise EmptyQueryError("no hay un id de serie válido para consultar")

        cache_key = f"series-detail:{raw}"
        cached = self._series_cache.get(cache_key)
        if cached is not None:
            logger.debug("cache HIT %s", cache_key)
            return cached

        detail = Series.from_payload(self._tvmaze.show_details(raw))
        self._series_cache.set(cache_key, detail)
        return detail

    def find_series(self, name: str) -> Series:
        """Primera serie que casa con *name*, con su detalle resuelto.

        :raises SeriesNotFoundError: si TVMaze no devuelve nada.
        :raises ApiContractError: si el primer resultado no trae objeto ``show``.
        """
        results = self._search_payloads(name)
        if not results:
            raise SeriesNotFoundError(name)

        first = results[0]
        show = first.get(TVMAZE_SHOW_KEY)
        if not isinstance(show, Mapping):
            raise ApiContractError("TVMaze devolvio un resultado sin el objeto 'show'")

        show_id = show.get(TVMAZE_SHOW_ID_KEY)
        if show_id is None:
            # Sin id no hay detalle posible: se devuelve el resumen tal cual.
            logger.debug("la serie %r no trae id; se omite el detalle", name)
            return Series.from_payload(first)
        return self.series_details(show_id)

    # -- diagnostico ---------------------------------------------------------
    def series_cache_stats(self) -> dict[str, float | int]:
        """Metricas de la cache de series."""
        return self._series_cache.stats().as_dict()

    def clear_caches(self) -> None:
        """Vacia la cache. Las metricas se conservan."""
        self._series_cache.clear()

    @property
    def config(self) -> AppConfig:
        return self._config

    def close(self) -> None:
        """Libera la conexion HTTP del cliente que se creo aqui."""
        self.clear_caches()
        if isinstance(self._tvmaze, HttpClient):
            self._tvmaze.close()

    def __enter__(self) -> SeriesService:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"SeriesService(timeout={self._config.request_timeout!r})"


__all__ = ["SeriesService"]