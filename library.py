"""Biblioteca local del usuario: favoritas, historial y persistencia.

Reemplaza a las globales ``PELICULAS_FAVORITAS`` e ``HISTORIAL_BUSQUEDAS`` de
``api_movies.py``, y a sus duplicadas homonimas en ``app.py``.

Tres decisiones de diseno que corrigen defectos concretos del original:

1. **Vistas inmutables.** ``favorites`` y ``history`` devuelven tuplas y
   ``MappingProxyType``, no las listas internas. Antes, ``main.py`` recebia la
   lista viva y podia mutarla; ahora la unica forma de cambiar la biblioteca es
   llamar a un metodo, que es donde se validan las reglas de negocio.
2. **Historial acotado y con fecha real.** El original no limitaba el historial
   (su propio docstring lo reconocia) y guardaba la cadena literal
   ``"hoy"`` como fecha. Ahora hay tope configurable y timestamp ISO 8601, con
   reloj inyectable.
3. **Import/export validado.** Antes un ``.json`` arbitrario asignaba el
   contenido directo a las globales sin comprobar nada.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from constants import OMDB_MOVIE_KEY

# El tope por defecto del historial es un valor de entorno (``MAX_HISTORY_ENTRIES``),
# asi que vive en ``config`` junto a ``AppConfig.from_env``, que es quien lo
# resuelve. ``config`` solo depende de la stdlib y de ``constants``, de modo que
# esta arista no introduce ningun ciclo.
from config import DEFAULT_MAX_HISTORY_ENTRIES
from exceptions import CorruptedStorageError, StorageError
from utils.validators import validate_safe_path

logger = logging.getLogger(__name__)

#: Formato de los archivos de la biblioteca.
JSON_ENCODING: str = "utf-8"
JSON_INDENT: int = 2

FAVORITES_KEY: str = "favoritas"
HISTORY_KEY: str = "historial"
STATS_KEY: str = "estadisticas"
SCHEMA_VERSION_KEY: str = "version"
SCHEMA_VERSION: int = 1

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Reloj por defecto. Inyectable para obtener historial determinista."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """Una entrada del historial de busquedas."""

    title: str
    searched_at: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "titulo": self.title,
            "fecha": self.searched_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HistoryEntry:
        """Reconstruye una entrada validando la fecha.

        :raises CorruptedStorageError: si la fecha no es ISO 8601.
        """
        raw_title = payload.get("titulo")
        raw_date = payload.get("fecha")
        if not isinstance(raw_title, str) or not isinstance(raw_date, str):
            raise CorruptedStorageError(
                f"entrada de historial con campos invalidos: {dict(payload)!r}"
            )
        try:
            moment = datetime.fromisoformat(raw_date)
        except ValueError as exc:
            raise CorruptedStorageError(
                f"fecha de historial no valida: {raw_date!r}"
            ) from exc
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return cls(title=raw_title, searched_at=moment)


@dataclass(frozen=True, slots=True)
class LibraryStats:
    """Contadores derivados de la biblioteca."""

    total_favorites: int
    total_history: int
    favorites_with_rating: float | None = None

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "total_favoritas": self.total_favorites,
            "total_historial": self.total_history,
        }
        if self.favorites_with_rating is not None:
            data["rating_medio_favoritas"] = round(self.favorites_with_rating, 2)
        return data


class MovieLibrary:
    """Coleccion personal de peliculas. Todo el estado es de instancia."""

    def __init__(
        self,
        *,
        max_history_entries: int = DEFAULT_MAX_HISTORY_ENTRIES,
        clock: Clock = utc_now,
    ) -> None:
        if max_history_entries <= 0:
            raise ValueError("max_history_entries debe ser > 0")
        if not callable(clock):
            raise TypeError("clock debe ser invocable")

        self._favorites: list[Mapping[str, Any]] = []
        self._history: list[HistoryEntry] = []
        self._max_history = int(max_history_entries)
        self._clock = clock

    # -- favoritas ---------------------------------------------------------
    @property
    def favorites(self) -> tuple[Mapping[str, Any], ...]:
        """Copia logica de las favoritas. Modificarla no afecta a la biblioteca."""
        return tuple(self._favorites)

    @property
    def history(self) -> tuple[HistoryEntry, ...]:
        return tuple(self._history)

    def add_favorite(self, movie: Mapping[str, Any]) -> bool:
        """Agrega *movie* a favoritas.

        :returns: ``True`` si se agrego, ``False`` si ya estaba.
        """
        title = movie_title(movie)
        if self.find_favorite(title) is not None:
            return False
        self._favorites.append(dict(movie))
        logger.debug("agregada a favoritas: %s", title)
        return True

    def remove_favorite(self, title: str) -> bool:
        """Elimina la favorita con ese titulo.

        :returns: ``True`` si se elimino algo.
        """
        target = title.strip().casefold()
        for index, movie in enumerate(self._favorites):
            if movie_title(movie).casefold() == target:
                # Se elimina por indice ya resuelto: el ``pop(i)`` dentro de un
                # ``for i in range(len(...))`` del original era fragil.
                del self._favorites[index]
                logger.debug("eliminada de favoritas: %s", title)
                return True
        return False

    def find_favorite(self, title: str) -> Mapping[str, Any] | None:
        """Devuelve la favorita con ese titulo, o ``None``."""
        target = title.strip().casefold()
        for movie in self._favorites:
            if movie_title(movie).casefold() == target:
                return movie
        return None

    def clear_favorites(self) -> None:
        self._favorites.clear()

    # -- historial ---------------------------------------------------------
    def add_to_history(self, movie: Mapping[str, Any], *, now: datetime | None = None) -> HistoryEntry:
        """Registra *movie* en el historial y descarta la entrada mas antigua.

        Ya no se duplica el bucle con ``fecha="hoy"`` del original.
        """
        entry = HistoryEntry(
            title=movie_title(movie),
            searched_at=now if now is not None else self._clock(),
        )
        self._history.append(entry)
        overflow = len(self._history) - self._max_history
        if overflow > 0:
            del self._history[:overflow]
            logger.debug("historial recortado a %d entradas", self._max_history)
        logger.debug("historial: +%s", entry.title)
        return entry

    def clear_history(self) -> None:
        """Vacia el historial.

        Antes esto reasignaba la global a una lista nueva; como ``main.py``
        sostenia una referencia a la lista anterior, el vaciado no se veia.
        """
        self._history.clear()

    # -- estadisticas ------------------------------------------------------
    def statistics(self) -> LibraryStats:
        """Contadores de la biblioteca.

        Sustituye a los dos bucles ``total = total + 1`` de
        ``api_movies.obtener_estadisticas``: aqui basta ``len()``.
        """
        ratings: list[float] = []
        for movie in self._favorites:
            raw = movie.get("imdbRating")
            if raw in (None, "", "N/A"):
                continue
            try:
                ratings.append(float(raw))
            except (TypeError, ValueError):
                # Se descarta solo el registro corrupto, no toda la coleccion.
                logger.debug("rating ilegible ignorado: %r", raw)

        average = sum(ratings) / len(ratings) if ratings else None
        return LibraryStats(
            total_favorites=len(self._favorites),
            total_history=len(self._history),
            favorites_with_rating=average,
        )

    # -- persistencia ------------------------------------------------------
    def export_to_json(self, path: str | Path) -> Path:
        """Vuelca la biblioteca a *path*.

        *path* se valida antes de tocar el disco: sin esa comprobacion, un
        ``path`` con ``..`` permitiria crear directorios y escribir fuera del
        directorio de trabajo.

        :raises EmptyQueryError: si *path* no es un nombre de archivo valido.
        :raises StorageError: si el archivo no se puede escribir.
        """
        target = validate_safe_path(path)
        payload = {
            SCHEMA_VERSION_KEY: SCHEMA_VERSION,
            FAVORITES_KEY: [dict(movie) for movie in self._favorites],
            HISTORY_KEY: [entry.as_dict() for entry in self._history],
            STATS_KEY: self.statistics().as_dict(),
        }
        try:
            if target.parent != Path(""):
                target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding=JSON_ENCODING) as handle:
                json.dump(payload, handle, indent=JSON_INDENT, ensure_ascii=False)
        except OSError as exc:
            raise StorageError(
                f"no se pudo escribir la biblioteca: {exc}", path=target
            ) from exc

        logger.info("biblioteca exportada a %s", target)
        return target

    def import_from_json(self, path: str | Path) -> tuple[int, int]:
        """Restaura la biblioteca desde *path*, reemplazando su contenido.

        El contenido anterior se conserva hasta que la lectura y la validacion
        terminan con exito, de modo que un archivo corrupto no deja la
        biblioteca a medias.

        :returns: ``(favoritas, historial)`` restaurados.
        :raises EmptyQueryError: si *path* no es un nombre de archivo valido.
        :raises StorageError: si el archivo no existe o no se puede leer.
        :raises CorruptedStorageError: si el JSON o su esquema no son validos.
        """
        source = validate_safe_path(path)
        try:
            with source.open("r", encoding=JSON_ENCODING) as handle:
                payload = json.load(handle)
        except FileNotFoundError as exc:
            raise StorageError(f"no existe el archivo: {source}", path=source) from exc
        except OSError as exc:
            raise StorageError(f"no se pudo leer {source}: {exc}", path=source) from exc
        except json.JSONDecodeError as exc:
            raise CorruptedStorageError(f"JSON invalido en {source}: {exc}", path=source) from exc

        favorites, history = self._parse_payload(payload, source)

        self._favorites = favorites
        self._history = history
        logger.info(
            "biblioteca restaurada desde %s (%d favoritas, %d historial)",
            source,
            len(favorites),
            len(history),
        )
        return len(favorites), len(history)

    def _parse_payload(
        self, payload: Any, source: Path
    ) -> tuple[list[Mapping[str, Any]], list[HistoryEntry]]:
        """Valida el esquema completo antes de tocar el estado de la instancia."""
        if not isinstance(payload, Mapping):
            raise CorruptedStorageError(
                f"se esperaba un objeto JSON en la raiz de {source}, "
                f"se recibio {type(payload).__name__}",
                path=source,
            )

        version = payload.get(SCHEMA_VERSION_KEY, SCHEMA_VERSION)
        if not isinstance(version, int) or version > SCHEMA_VERSION:
            raise CorruptedStorageError(
                f"version de esquema no soportada en {source}: {version!r}", path=source
            )

        raw_favorites = payload.get(FAVORITES_KEY, [])
        if not isinstance(raw_favorites, Sequence) or isinstance(raw_favorites, (str, bytes)):
            raise CorruptedStorageError(
                f"'{FAVORITES_KEY}' debe ser una lista en {source}", path=source
            )

        favorites: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        for item in raw_favorites:
            if not isinstance(item, Mapping):
                raise CorruptedStorageError(
                    f"cada favorita debe ser un objeto en {source}: {item!r}", path=source
                )
            title = movie_title(item)
            key = title.casefold()
            if key in seen:
                logger.debug("favorita duplicada en el archivo, se ignora: %s", title)
                continue
            seen.add(key)
            favorites.append(dict(item))

        raw_history = payload.get(HISTORY_KEY, [])
        if not isinstance(raw_history, Sequence) or isinstance(raw_history, (str, bytes)):
            raise CorruptedStorageError(
                f"'{HISTORY_KEY}' debe ser una lista en {source}", path=source
            )

        history = [HistoryEntry.from_dict(item) for item in raw_history]
        if len(history) > self._max_history:
            history = history[-self._max_history :]

        return favorites, history

    def __repr__(self) -> str:
        return (
            f"MovieLibrary(favorites={len(self._favorites)}, "
            f"history={len(self._history)}, max_history={self._max_history})"
        )


__all__ = [
    "HistoryEntry",
    "LibraryStats",
    "MovieLibrary",
    "movie_title",
    "utc_now",
]


def movie_title(movie: Mapping[str, Any]) -> str:
    """Extrae el titulo de una ficha, aceptando cualquiera de las dos formas.

    OMDb usa ``"Title"`` y el catalogo local ``"titulo"``. Antes cada modulo
    asumia una u otra, y por eso una pelicula guardada desde el menu de actor
    aparecia con el titulo vacio en el historial.
    """
    value = movie.get(OMDB_MOVIE_KEY) or movie.get("titulo") or ""
    return str(value).strip()