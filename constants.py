"""Constantes de dominio y de presentacion del catalogo de peliculas y series.

Este modulo es intencionalmente inerte: no lee disco, no lee variables de
entorno, no abre sockets y no importa dependencias externas. Solo define
valores, de modo que importarlo nunca pueda producir un efecto secundario.

Reparto con :mod:`config`:

* Aqui viven los valores **fijos**: endpoints, rutas, claves del esquema de
  datos, catálogos, formato de presentacion y codigos de salida.
* En :mod:`config` viven los valores **variables**: todo lo que el entorno
  pueda cambiar mediante ``OMDB_TIMEOUT``, ``CACHE_TTL_SECONDS``, etc., junto
  con sus valores por defecto.

Sustituye a los 88 modulos ``*_config.py`` que existian antes, de los cuales
ninguno era importado por el proyecto.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping, NamedTuple

# --------------------------------------------------------------------------
# Endpoints
#
# Nota de seguridad: las URLs de origen usaban ``http://`` en claro. Se
#abandonan en favor de ``https://`` para que la clave de API y los
#titulos consultados viajen cifrados.
# --------------------------------------------------------------------------
OMDB_BASE_URL: Final[str] = "https://www.omdbapi.com/"
TVMAZE_BASE_URL: Final[str] = "https://api.tvmaze.com"

OMDB_PATH: Final[str] = ""
TVMAZE_SEARCH_PATH: Final[str] = "/search/shows"
TVMAZE_SHOW_PATH: Final[str] = "/shows"

#: Tope defensivo de paginacion para las busquedas de OMDb. OMDb pagina de 10
#: en 10; este limite evita un bucle infinito si el total announcing no cuadra.
OMDB_MAX_SEARCH_PAGES: Final[int] = 10


# --------------------------------------------------------------------------
# Presentacion
# --------------------------------------------------------------------------
SEPARATOR_CHAR: Final[str] = "="
SEPARATOR_WIDTH: Final[int] = 60
NOT_AVAILABLE: Final[str] = "N/A"
SUMMARY_MAX_LENGTH: Final[int] = 200
EMPTY_VALUE: Final[str] = ""

#: Longitud maxima del cuerpo de un error HTTP en el mensaje de la excepcion.
#: Coincide con ``SUMMARY_MAX_LENGTH`` pero es otro concepto: uno recorta lo que
#: se muestra, el otro lo que se registra, asi que no se reutiliza el mismo.
HTTP_ERROR_DETAIL_MAX_LENGTH: Final[int] = 200

#: Los indices que el usuario ve en las listas empiezan en 1, no en 0, porque
#: el 0 esta reservado para "volver".
FIRST_LIST_OPTION: Final[int] = 1


# --------------------------------------------------------------------------
# Codigos de salida del proceso
# --------------------------------------------------------------------------
EXIT_SUCCESS: Final[int] = 0
EXIT_ERROR: Final[int] = 1
#: 130 es el codigo reservado por POSIX para "terminado por SIGINT".
EXIT_INTERRUPTED: Final[int] = 130

#: Numero de la opcion "Salir" en el menu principal.
EXIT_OPTION: Final[int] = 12


# --------------------------------------------------------------------------
# Esquema de datos de las APIs
#
# ``OMDB_MOVIE_FIELDS`` y ``TVMAZE_SHOW_FIELDS`` sustituyen a los 9 bloques
# ``try/except`` duplicados que tenia ``main.py.mostrar_pelicula`` y a los 11
# de ``utils.format_movie_display``. Son tuplas inmutables de pares
# ``(clave_remota, etiqueta_local)``; el acceso a claves anidadas se resuelve
# con notacion de punto (``"rating.average"``).
# --------------------------------------------------------------------------
OMDB_MOVIE_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("Title", "Titulo"),
    ("Year", "Anio"),
    ("imdbRating", "Rating IMDB"),
    ("Genre", "Genero"),
    ("Director", "Director"),
    ("Actors", "Actores"),
    ("Plot", "Trama"),
    ("Language", "Idioma"),
    ("Country", "Pais"),
    ("Awards", "Premios"),
    ("Poster", "Poster"),
)

TVMAZE_SHOW_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("name", "Nombre"),
    ("language", "Idioma"),
    ("genres", "Generos"),
    ("rating.average", "Rating"),
    ("status", "Estado"),
    ("premiered", "Estreno"),
    ("ended", "Finalizacion"),
    ("runtime", "Episodios"),
    ("summary", "Resumen"),
)

#: Claves por las que se distingue la forma de un item del catalogo local
#: (``"titulo"``) de la de un resultado de OMDB (``"Title"``).
LOCAL_MOVIE_KEY: Final[str] = "titulo"
OMDB_MOVIE_KEY: Final[str] = "Title"
TVMAZE_SHOW_KEY: Final[str] = "show"
TVMAZE_SHOW_ID_KEY: Final[str] = "id"


# --------------------------------------------------------------------------
# Catalogo local de respaldo
#
# Estas peliculas nunca dependieron de la red: antes vivian hardcodeadas y
# duplicadas en ``api_movies.obtener_peliculas_populares`` y
# ``app.obtener_peliculas_populares``. Ahora viven una sola vez, aqui, como
# NamedTuple inmutable.
# --------------------------------------------------------------------------
class LocalMovie(NamedTuple):
    """Pelicula del catalogo local, sin identificador remoto."""

    title: str
    year: int
    rating: float


POPULAR_MOVIES: Final[tuple[LocalMovie, ...]] = (
    LocalMovie("The Shawshank Redemption", 1994, 9.3),
    LocalMovie("The Godfather", 1972, 9.2),
    LocalMovie("The Dark Knight", 2008, 9.0),
    LocalMovie("Pulp Fiction", 1994, 8.9),
    LocalMovie("Forrest Gump", 1994, 8.8),
)

MOVIES_BY_GENRE: Final[Mapping[str, tuple[LocalMovie, ...]]] = MappingProxyType(
    {
        "accion": (
            LocalMovie("Die Hard", 1988, 8.2),
            LocalMovie("Mad Max Fury Road", 2015, 8.1),
        ),
        "comedia": (
            LocalMovie("Superbad", 2007, 7.6),
            LocalMovie("The Hangover", 2009, 7.7),
        ),
    }
)

GENRE_LABELS: Final[tuple[str, ...]] = tuple(MOVIES_BY_GENRE)