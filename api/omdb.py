"""Cliente de OMDb (peliculas).

Solo se ocupa de hablar con ``https://www.omdbapi.com``: construir los
parametros, interpretar su formato de respuesta (marca ``Response`` y
paginacion de ``Search``) y declarar sus endpoints.

No contiene logica de negocio ni de presentacion: convertir estas respuestas en
objetos :class:`~models.movie.Movie` es tarea de
:class:`~services.movie_service.MovieService`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Final

from api.base import HttpClient, JsonObject, expect_object, require_text
from constants import OMDB_MAX_SEARCH_PAGES, OMDB_PATH
from exceptions import ApiContractError, MovieNotFoundError

logger = logging.getLogger(__name__)

#: Nombre con el que se identifica a esta API en los mensajes de error.
API_NAME: Final[str] = "OMDb"

#: Valor de ``Response`` con el que OMDb confirma un hallazgo.
OMDB_FOUND_FLAG: Final[str] = "True"

#: ``path`` del endpoint raiz de OMDb. Se usa como nombre de endpoint en los
#: errores, donde una cadena vacia no seria util, de ahi el ``or "/"``.
_ENDPOINT_LABEL: Final[str] = OMDB_PATH or "/"


def _as_int(value: Any) -> int | None:
    """Convierte a ``int`` si es posible; si no, devuelve ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


class OmdbClient(HttpClient):
    """Cliente de OMDb (peliculas). Requiere ``apikey``."""

    def search_by_title(self, title: str) -> JsonObject | None:
        """Busca una pelicula por titulo exacto.

        :returns: la ficha, o ``None`` si OMDb responde ``Response=False``.
        :raises EmptyQueryError: si *title* es blanco.
        """
        query = require_text(title, "titulo")
        payload = expect_object(
            self.get_json(OMDB_PATH, {"t": query}), endpoint=_ENDPOINT_LABEL, api=API_NAME
        )
        if payload.get("Response") == OMDB_FOUND_FLAG:
            return payload
        logger.debug("%s no encontro la pelicula %r (%s)", API_NAME, query, payload.get("Error"))
        return None

    def search_by_actor(self, actor: str) -> tuple[JsonObject, ...]:
        """Busca peliculas por actor, paginando hasta agotar el resultado.

        OMDb limita cada pagina a 10 resultados, asi que esta funcion itera
        sobre ``page``. Antes solo devolvia la primera pagina.
        """
        query = require_text(actor, "actor")
        collected: list[JsonObject] = []
        total: int | None = None
        page = 1
        while True:
            payload = expect_object(
                self.get_json(OMDB_PATH, {"s": query, "type": "movie", "page": str(page)}),
                endpoint=_ENDPOINT_LABEL,
                api=API_NAME,
            )
            if payload.get("Response") != OMDB_FOUND_FLAG:
                break

            batch = payload.get("Search") or ()
            if not isinstance(batch, Sequence) or isinstance(batch, (str, bytes)):
                raise ApiContractError(
                    f"{API_NAME} devolvio 'Search' con tipo inesperado: "
                    f"{type(batch).__name__}",
                    endpoint=_ENDPOINT_LABEL,
                )

            collected.extend(item for item in batch if isinstance(item, Mapping))
            total = _as_int(payload.get("totalResults"))
            if total is not None and len(collected) >= total:
                break
            if not batch:
                break
            page += 1
            if page > OMDB_MAX_SEARCH_PAGES:
                logger.warning(
                    "paginacion de %s detenida en la pagina %d (tope defensivo)",
                    API_NAME, page,
                )
                break

        # OMDb anuncia `totalResults` pero la ultima pagina puede traer mas de
        # los que quedan: se recorta para no devolver duplicados de mas.
        if total is not None:
            collected = collected[:total]

        logger.debug("%s devolvio %d peliculas para el actor %r", API_NAME, len(collected), query)
        return tuple(collected)

    def fetch_detail(self, title: str) -> JsonObject:
        """Como :meth:`search_by_title`, pero lanza excepcion si no encuentra.

        :raises MovieNotFoundError: si OMDb responde ``Response=False``.
        """
        movie = self.search_by_title(title)
        if movie is None:
            raise MovieNotFoundError(title)
        return movie