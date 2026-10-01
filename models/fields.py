"""Modelo de pelicula.

:func:`resolve_field` y la clase :class:`Movie` comparten la logica de leer un
campo por ruta con puntos (``"rating.average"``). El modelo la expone para que
las demas capas no tengan que duplicarla.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from constants import NOT_AVAILABLE


def resolve_field(payload: Mapping[str, Any], path: str, default: Any = NOT_AVAILABLE) -> Any:
    """Lee *path* de *payload* admitiendo notacion de punto.

    Devuelve *default* ante cualquier clave ausente o ``None`` intermedio.

    :param payload: objeto del que leer.
    :param path: clave, o ruta de claves separadas por ``.``.
    :param default: valor a devolver si la ruta no resuelve.
    """
    current: Any = payload
    for segment in path.split("."):
        if not isinstance(current, Mapping):
            return default
        if segment not in current:
            return default
        current = current[segment]
    return default if current is None else current