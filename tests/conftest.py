"""Fixtures compartidas por toda la suite.

Solo datos y objetos sin comportamiento de red. Los dobles de ``requests`` y
los relojes falsos viven en ``unit/conftest.py``, porque son cosa de los tests
unitarios.

Ninguna fixture contiene una credencial real. La clave de OMDb que usan los
tests es un literal ficticio declarado aqui, no algo tomado del entorno.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from config import AppConfig
from models.movie import Movie
from models.series import Series

#: Credencial ficticia. No es una clave valida de nadie: los tests unitarios
#: nunca salen a la red, asi que su valor es irrelevante, y las integraciones
#: la rechazan por el marker y por `skipif`.
FAKE_API_KEY = "clave-ficticia-de-prueba"

#: Peticion estable de OMDb. "Interstellar" lleva años en su catalogo y no va a
#: desaparecer, a diferencia de peliculas de reciente estreno.
OMDB_STABLE_TITLE = "Interstellar"

#: Serie estable de TVMaze. Es publica y no requiere credencial.
TVMAZE_STABLE_SHOW = "Breaking Bad"


# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
@pytest.fixture
def env_limpio(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Elimina del entorno real las variables que lee ``AppConfig``.

    Se usa junto a ``AppConfig.from_env(env=...)``, que recibe el entorno por
    parametro, para que ningun test dependa de lo que el desarrollador tenga
    exportado en su shell.
    """
    for nombre in (
        "OMDB_API_KEY",
        "OMDB_TIMEOUT",
        "OMDB_MAX_RETRIES",
        "CACHE_TTL_SECONDS",
        "CACHE_MAX_ENTRIES",
        "MAX_HISTORY_ENTRIES",
        "APP_DEBUG",
        "APP_VERBOSE",
    ):
        monkeypatch.delenv(nombre, raising=False)
    yield


@pytest.fixture
def config(env_limpio: None) -> AppConfig:
    """Configuracion de test: clave falsa y caches minsimas.

    Las caches son de 2 entradas para que los tests de eviction no dependan de
    insertar 256 elementos.
    """
    return AppConfig(
        omdb_api_key=FAKE_API_KEY,
        request_timeout=1.0,
        max_retries=0,
        cache_ttl_seconds=60,
        cache_max_entries=2,
        max_history_entries=3,
    )


# ---------------------------------------------------------------------------
# Payloads crudos de OMDb
#
# Sondicciones planas con la forma que devuelve la API. Se usan en los tests de
# `api/omdb.py` y en los de los servicios, para que ambos niveles se apoyen en
# el mismo ejemplo.
# ---------------------------------------------------------------------------
@pytest.fixture
def omdb_pelicula_encontrada() -> dict[str, Any]:
    """Respuesta 200 de ``?t=``: una ficha completa."""
    return {
        "Title": "Interstellar",
        "Year": "2014",
        "Rated": "PG-13",
        "Released": "07 Nov 2014",
        "Runtime": "169 min",
        "Genre": "Adventure, Drama, Science Fiction",
        "Director": "Christopher Nolan",
        "Actors": "Matthew McConaughey, Anne Hathaway",
        "Plot": "Un equipo de exploradores viaja por un agujero de gusano.",
        "Language": "English",
        "Country": "USA",
        "imdbRating": "8.7",
        "imdbID": "tt0816692",
        "Type": "movie",
        "Poster": "https://example.invalid/poster.jpg",
        "Response": "True",
    }


@pytest.fixture
def omdb_pelicula_no_encontrada() -> dict[str, Any]:
    """Respuesta 200 de ``?t=`` con ``Response=False``: no hay resultado."""
    return {"Response": "False", "Error": "Movie not found!"}


@pytest.fixture
def omdb_busqueda_actor_pagina_1() -> dict[str, Any]:
    """Pagina de ``?s=`` que ya esta completa: 3 anunciados, 3 entregados.

    ``totalResults`` coincide con lo entregado a proposito. Asi la paginacion se
    detiene en la primera pagina y el fixture es utilizable tal cual, sin un
    servidor que siga respondiendo. Para probar varias paginas, los tests
    sobreescriben ``totalResults`` con la suma de ambas.
    """
    return {
        "Search": [
            {"Title": "A", "Year": "1999", "imdbID": "tt1", "Type": "movie"},
            {"Title": "B", "Year": "2000", "imdbID": "tt2", "Type": "movie"},
            {"Title": "C", "Year": "2001", "imdbID": "tt3", "Type": "movie"},
        ],
        "totalResults": "3",
        "Response": "True",
    }


@pytest.fixture
def omdb_busqueda_actor_pagina_2() -> dict[str, Any]:
    """Segunda pagina: otros 3 titulos, para el escenario de dos paginas.

    ``totalResults`` es igualmente "3". El test que la usa lo sube a "6", la
    suma de las dos paginas, que es como el cliente decide seguir asking.
    """
    return {
        "Search": [
            {"Title": "D", "Year": "2002", "imdbID": "tt4", "Type": "movie"},
            {"Title": "E", "Year": "2003", "imdbID": "tt5", "Type": "movie"},
            {"Title": "F", "Year": "2004", "imdbID": "tt6", "Type": "movie"},
        ],
        "totalResults": "3",
        "Response": "True",
    }


# ---------------------------------------------------------------------------
# Payloads crudos de TVMaze
# ---------------------------------------------------------------------------
@pytest.fixture
def tvmaze_show() -> dict[str, Any]:
    """Objeto ``show`` plano, tal cual lo devuelve ``/shows/{id}``."""
    return {
        "id": 1698,
        "name": "Breaking Bad",
        "language": "English",
        "genres": ["Drama", "Crime"],
        "status": "Ended",
        "premiered": "2008-01-20",
        "ended": "2013-09-29",
        "runtime": 47,
        "summary": "<p>Un profesor de quimica se convierte en fabricante de metanfetamina.</p>",
        "rating": {"average": 9.3},
    }


@pytest.fixture
def tvmaze_busqueda(tvmaze_show: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Respuesta de ``/search/shows``: una **lista** con envoltorio ``show``.

    El envoltorio es lo que la API envia en este endpoint y lo que
    ``Series.from_payload`` desenvuelve. El detalle viene plano. Que las dos
    formas coexistan es justo lo que hay que probar.
    """
    return [{"score": 0.1, "show": dict(tvmaze_show)}]


# ---------------------------------------------------------------------------
# Modelos ya construidos
# ---------------------------------------------------------------------------
@pytest.fixture
def movie(omdb_pelicula_encontrada: Mapping[str, Any]) -> Movie:
    """``Movie`` sobre el payload de una pelicula encontrada."""
    return Movie.from_payload(omdb_pelicula_encontrada)


@pytest.fixture
def series(tvmaze_busqueda: list[dict[str, Any]]) -> Series:
    """``Series`` sobre el primer resultado de la busqueda."""
    return Series.from_payload(tvmaze_busqueda[0])


# ---------------------------------------------------------------------------
# Ayudas
# ---------------------------------------------------------------------------
@pytest.fixture
def movie_en_crudo(omdb_pelicula_encontrada: Mapping[str, Any]) -> dict[str, Any]:
    """Copia mutable del payload, para ``MovieLibrary``, que guarda mapeos."""
    return dict(omdb_pelicula_encontrada)
