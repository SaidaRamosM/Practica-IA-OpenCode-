"""Modelo de serie.

El atributo set refleja lo que la aplicacion **muestra**: las 9 rutas de
:data:`constants.TVMAZE_SHOW_FIELDS`, mas el ``id`` que se necesita para pedir
el detalle de una serie.

TVMaze devuelve dos envolturas distintas segun el endpoint: ``{"show": {...}}``
en las busquedas y el objeto plano en ``/shows/{id}``.
:meth:`Series.from_payload` normaliza ambas al show desenvuelto, porque
:func:`api.tvmaze.extract_show` es idempotente: aplicarlo a un show ya plano lo
devuelve sin cambios. Asi, marcar la serie ya no distingue entre las dos formas.

Al igual que :class:`~models.movie.Movie`, este modelo **envuelve** el payload en
lugar de sustituirlo, para no alterar ni la salida por pantalla ni el JSON.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from constants import NOT_AVAILABLE, TVMAZE_SHOW_ID_KEY, TVMAZE_SHOW_KEY
from models.fields import resolve_field


def extract_show(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Devuelve el objeto ``show`` de una respuesta de TVMaze.

    Acepta tanto ``{"show": {...}}`` (lo que devuelve ``/search/shows``) como el
    objeto plano (lo que devuelve ``/shows/{id}``). Es idempotente: aplicarlo a
    un show ya desenvuelto lo devuelve sin cambios.

    Vive en :mod:`models` y no en :mod:`api.tvmaze` porque no es conocimiento
    de red sino de forma de datos: interpretarlo forma parte de construir un
    :class:`Series`. Ademas evita que los modelos dependan de la capa de API.
    """
    inner = payload.get(TVMAZE_SHOW_KEY)
    if isinstance(inner, Mapping):
        return inner
    return payload


@dataclass(frozen=True, slots=True)
class Series:
    """Serie, con vista tipada sobre el payload de TVMaze.

    :param raw: objeto ``show`` ya desenvuelto.
    """

    raw: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Series:
        """Normaliza *payload* y lo envuelve.

        Acepta tanto ``{"show": {...}}`` como el objeto plano y guarda siempre el
        show desenvuelto.
        """
        return cls(raw=extract_show(payload))

    # -- acceso por ruta (lo usa la presentacion) -------------------------
    def get(self, path: str, default: Any = NOT_AVAILABLE) -> Any:
        """Resuelve *path* sobre el payload crudo. Ver :func:`resolve_field`."""
        return resolve_field(self.raw, path, default)

    def to_dict(self) -> dict[str, Any]:
        """Copia del show desenvuelto."""
        return dict(self.raw)

    # -- atributos tipados --------------------------------------------------
    @property
    def id(self) -> Any | None:
        """Identificador de TVMaze, necesario para pedir el detalle."""
        return self.raw.get(TVMAZE_SHOW_ID_KEY)

    @property
    def title(self) -> str:
        """Nombre de la serie. TVMaze lo llama ``name``."""
        return str(self.get("name", ""))

    @property
    def language(self) -> str:
        return str(self.get("language", NOT_AVAILABLE))

    @property
    def genres(self) -> list[Any]:
        """Generos. TVMaze los devuelve como lista; puede venir vacia."""
        value = self.get("genres", [])
        return list(value) if isinstance(value, list) else []

    @property
    def rating(self) -> str:
        """Puntuacion media. TVMaze la anida en ``rating.average``."""
        return str(self.get("rating.average", NOT_AVAILABLE))

    @property
    def status(self) -> str:
        return str(self.get("status", NOT_AVAILABLE))

    @property
    def premiered(self) -> str:
        return str(self.get("premiered", NOT_AVAILABLE))

    @property
    def ended(self) -> str:
        return str(self.get("ended", NOT_AVAILABLE))

    @property
    def runtime(self) -> str:
        """Duracion por episodio, en minutos."""
        return str(self.get("runtime", NOT_AVAILABLE))

    @property
    def summary(self) -> str:
        """Resumen. TVMaze lo devuelve con etiquetas HTML."""
        return str(self.get("summary", NOT_AVAILABLE))


__all__ = ["Series", "extract_show"]