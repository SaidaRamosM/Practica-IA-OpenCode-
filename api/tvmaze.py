"""Cliente de TVMaze (series).

Solo se ocupa de hablar con ``https://api.tvmaze.com``: construir las
solicitudes, interpretar su formato (envoltorio ``{"show": {...}}`` y detalle
plano) y declarar sus endpoints.

TVMaze es una API publica: no requiere clave, a diferencia de OMDb.

No contiene logica de negocio ni de presentacion: convertir estas respuestas en
objetos :class:`~models.series.Series` es tarea de
:class:`~services.series_service.SeriesService`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Final

from api.base import HttpClient, JsonObject, expect_array, expect_object, require_text
from constants import (
    TVMAZE_SEARCH_PATH,
    TVMAZE_SHOW_PATH,
)
from exceptions import EmptyQueryError

logger = logging.getLogger(__name__)

#: Nombre con el que se identifica a esta API en los mensajes de error.
API_NAME: Final[str] = "TVMaze"


class TvmazeClient(HttpClient):
    """Cliente de TVMaze (series). Es una API publica: no requiere key."""

    def search_shows(self, name: str) -> tuple[JsonObject, ...]:
        """Busca series por nombre.

        TVMaze responde con un **array JSON en la raiz** en este endpoint, no
        con un objeto: por eso se valida con :func:`~api.base.expect_array`. Cada
        elemento mantiene su envoltorio ``{"show": {...}}``, tal como lo envia
        la API.

        :returns: tupla de envoltorios, o vacia si no hay coincidencias.
        """
        query = require_text(name, "nombre de serie")
        payload = expect_array(
            self.get_json(TVMAZE_SEARCH_PATH, {"q": query}),
            endpoint=TVMAZE_SEARCH_PATH,
            api=API_NAME,
        )
        found = tuple(item for item in payload if isinstance(item, Mapping))
        logger.debug("%s devolvio %d series para %r", API_NAME, len(found), query)
        return found

    def show_details(self, show_id: int | str) -> JsonObject:
        """Detalle de una serie a partir de su id.

        :raises EmptyQueryError: si *show_id* esta vacio.
        """
        raw = str(show_id).strip()
        if not raw or raw == "None":
            raise EmptyQueryError("no hay un id de serie válido para consultar")
        path = f"{TVMAZE_SHOW_PATH}/{raw}"
        return expect_object(self.get_json(path), endpoint=path, api=API_NAME)