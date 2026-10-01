"""Modelo de pelicula.

El atributo set refleja lo que la aplicacion **muestra y almacena**, derivado de
las 11 rutas de :data:`constants.OMDB_MOVIE_FIELDS` mas las que consultan
:mod:`library` (``Title`` e ``imdbRating``).

Decision de diseno: ``Movie`` **envuelve** el payload crudo en vez de sustituirlo.
Motivo: el proyecto debe mantener *exactamente* el mismo comportamiento, y tanto
la salida por pantalla como el JSON exportado se derivan del payload original.
Convertirlo a dataclass plano obligaria a renombrar claves y etiquetas, con riesgo
de alterar el formato. Por eso el modelo ofrece dos accesos:

* propiedades con nombre (``movie.title``), que son el contrato legible para
  servicios y pruebas;
* :meth:`Movie.get`, que resuelve rutas y es lo que usa la capa de presentacion,
  de modo que la tabla de etiquetas sigue siendo la unica fuente del formato.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from constants import (
    LOCAL_MOVIE_KEY,
    NOT_AVAILABLE,
    OMDB_MOVIE_KEY,
    OMDB_MOVIE_FIELDS,
)
from models.fields import resolve_field


@dataclass(frozen=True, slots=True)
class Movie:
    """Pelicula, con vista tipada sobre el payload de OMDb.

    :param raw: objeto JSON tal cual lo devolvio OMDb. Se conserva sin
        modificar para no alterar lo que se muestra ni lo que se exporta.
    """

    raw: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Movie:
        """Envuelve *payload* sin transformarlo.

        No hay conversion ni normalizacion: el proposito es dar nombre a las
        claves, no cambiarlas.
        """
        return cls(raw=payload)

    # -- acceso por ruta (lo usa la presentacion) -------------------------
    def get(self, path: str, default: Any = NOT_AVAILABLE) -> Any:
        """Resuelve *path* sobre el payload crudo. Ver :func:`resolve_field`."""
        return resolve_field(self.raw, path, default)

    def to_dict(self) -> dict[str, Any]:
        """Copia del payload, para exportar o serializar.

        Identica a lo que se guardaba antes de existir este modelo, de modo que
        el JSON exportado no cambia.
        """
        return dict(self.raw)

    # -- atributos tipados --------------------------------------------------
    @property
    def title(self) -> str:
        """Titulo. OMDb lo llama ``Title``."""
        return str(self.get(OMDB_MOVIE_KEY, ""))

    @property
    def year(self) -> str:
        """Anio de lanzamiento, como cadena (OMDb lo devuelve asi)."""
        return str(self.get("Year", ""))

    @property
    def imdb_rating(self) -> str:
        """Puntuacion de IMDb, o ``"N/A"``."""
        return str(self.get("imdbRating", NOT_AVAILABLE))

    @property
    def genre(self) -> str:
        return str(self.get("Genre", NOT_AVAILABLE))

    @property
    def director(self) -> str:
        return str(self.get("Director", NOT_AVAILABLE))

    @property
    def actors(self) -> str:
        return str(self.get("Actors", NOT_AVAILABLE))

    @property
    def plot(self) -> str:
        return str(self.get("Plot", NOT_AVAILABLE))

    @property
    def language(self) -> str:
        return str(self.get("Language", NOT_AVAILABLE))

    @property
    def country(self) -> str:
        return str(self.get("Country", NOT_AVAILABLE))

    @property
    def awards(self) -> str:
        return str(self.get("Awards", NOT_AVAILABLE))

    @property
    def poster(self) -> str:
        return str(self.get("Poster", NOT_AVAILABLE))

    @classmethod
    def from_local(cls, title: str, year: Any, rating: Any) -> Movie:
        """Construye una pelicula del catalogo local.

        Usa la clave ``"titulo"`` (y no ``"Title"``) porque es la que la
        presentacion usa para distinguir una entrada local de una ficha de
        OMDb. Permite tratar ambos con el mismo modelo sin cambiar el formato.

        :param title: titulo.
        :param year: anio.
        :param rating: puntuacion.
        """
        return cls(raw={LOCAL_MOVIE_KEY: title, "anio": year, "rating": rating})


__all__ = ["Movie", "OMDB_MOVIE_FIELDS"]