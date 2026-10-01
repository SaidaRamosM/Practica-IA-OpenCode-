"""Composition root de la aplicacion.

:class:`Session` es el unico objeto que sabe como se conectan las piezas:
configuracion, servicios, biblioteca y presentacion. Vive fuera de ``main.py``
para que el punto de entrada se limite a arrancar, y fuera de ``ui`` porque
construir el grafo de objetos no es una responsabilidad de presentacion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config import AppConfig
from library import MovieLibrary
from services import MovieService, SeriesService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Session:
    """Configuracion y servicios de una ejecucion.

    Es inmutable. Cuando la configuracion cambia se construye una sesion
    nueva, de modo que ningun servicio puede observar un cambio parcial ni
    quedar con una configuracion obsoleta.
    """

    config: AppConfig
    movies: MovieService
    series: SeriesService
    library: MovieLibrary

    @classmethod
    def build(cls, config: AppConfig) -> Session:
        """Construye una sesion completa a partir de *config*."""
        logger.info(
            "construyendo sesion: timeout=%ss ttl_cache=%ss",
            config.request_timeout, config.cache_ttl_seconds,
        )
        return cls(
            config=config,
            movies=MovieService(config),
            series=SeriesService(config),
            library=MovieLibrary(max_history_entries=config.max_history_entries),
        )

    def rebuild_with(self, config: AppConfig) -> Session:
        """Devuelve una sesion nueva con *config*, conservando la biblioteca.

        Las favoritas y el historial son datos del usuario, no configuracion:
        se mantienen aunque se cambie el timeout o el TTL de la cache. Los
        servicios si se reconstruyen, porque capturan la configuracion en el
        momento de construirse.
        """
        logger.info(
            "reconstruyendo servicios: timeout=%ss ttl_cache=%ss (se conserva la biblioteca)",
            config.request_timeout, config.cache_ttl_seconds,
        )
        self.close()
        return Session(
            config=config,
            movies=MovieService(config),
            series=SeriesService(config),
            library=self.library,
        )

    def cache_stats(self) -> dict[str, dict[str, float | int]]:
        """Metricas de las tres caches, con las claves de siempre.

        Antes vivia esto en ``MovieCatalog``. Las claves ``movies``, ``series``
        y ``local`` son las que imprime la opcion 8 del menu, asi que se
        reconstruyen aqui para que la division del servicio no las altere.
        """
        return {
            "movies": self.movies.movie_cache_stats(),
            "series": self.series.series_cache_stats(),
            "local": self.movies.local_cache_stats(),
        }

    def close(self) -> None:
        """Libera las conexiones HTTP de los servicios."""
        self.movies.close()
        self.series.close()