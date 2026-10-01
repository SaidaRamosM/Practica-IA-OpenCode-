"""Presentacion por consola: formateo de peliculas, series y listados.

Regla de este modulo: **devuelve** lineas de texto, no las imprime. Quien
imprime es :mod:`ui.menu`, que ademas pide la entrada al usuario. Asi el
formateo se puede probar sin capturar ``stdout``.

Las funciones ``render_*`` son puras y no conocen ni la red ni la
configuracion. Los nombres de campo y sus etiquetas salen de
:mod:`constants`, de modo que ampliar las columnas es editar una tupla.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, Mapping
from html import unescape
from typing import Any

from constants import (
    EMPTY_VALUE,
    LOCAL_MOVIE_KEY,
    NOT_AVAILABLE,
    OMDB_MOVIE_KEY,
    OMDB_MOVIE_FIELDS,
    SEPARATOR_CHAR,
    SEPARATOR_WIDTH,
    SUMMARY_MAX_LENGTH,
    TVMAZE_SHOW_FIELDS,
    LocalMovie,
)
from models.fields import resolve_field
from models.series import extract_show

logger = logging.getLogger("peliculas.ui")

__all__ = [
    "configure_logging",
    "configure_output",
    "print_lines",
    "render_favorites",
    "render_fields",
    "render_header",
    "render_history",
    "render_local_movies",
    "render_movie",
    "render_movie_stub",
    "render_omdb_movies",
    "render_separator",
    "render_series",
    "render_series_results",
    "resolve_field",
    "show_cancelled",
    "show_communication_error",
    "show_config_error",
    "show_data_error",
    "show_interrupted",
    "show_startup_error",
]


# --------------------------------------------------------------------------
# Configuracion de la consola
# --------------------------------------------------------------------------
def configure_output() -> None:
    """Fuerza UTF-8 con reemplazo en la salida, para no morir en consola.

    Sin esto, una ficha con un caracter fuera de la ventana de la consola (por
    ejemplo un titulo con cirilico o un emoji en el poster) provoca un
    ``UnicodeEncodeError`` que aborta la aplicacion a mitad de un listado.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # Consola legacy o stream ya cerrado: se continua con la
            # codificacion por defecto en lugar de impedir el arranque.
            logger.debug("no se pudo reconfigurar %s a UTF-8", stream, exc_info=True)


def configure_logging(debug: bool, verbose: bool) -> None:
    """Configura ``logging`` segun los flags. Sustituye a los 158 ``print``."""
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


# --------------------------------------------------------------------------
# Piezas basicas de formato
# --------------------------------------------------------------------------
def render_separator(char: str = SEPARATOR_CHAR, width: int = SEPARATOR_WIDTH) -> str:
    """Linea horizontal. Sustituye a las 3 copias de ``print_separator``."""
    return char * width


def render_header(text: str, width: int = SEPARATOR_WIDTH) -> list[str]:
    """Encabezado centrado entre dos separadores."""
    return [
        render_separator(width=width),
        text.upper().center(width),
        render_separator(width=width),
    ]


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "..."


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Quita etiquetas HTML y desescapa entidades.

    TVMaze envuelve el resumen en ``<p>``/``<b>``. La version anterior lo
    imprimia tal cual, asi que el usuario leia markup en la consola.
    """
    if "<" not in text:
        return text
    return unescape(_TAG_RE.sub(" ", text)).strip()


def render_fields(
    payload: Mapping[str, Any],
    fields: Iterable[tuple[str, str]],
    *,
    max_length: int = SUMMARY_MAX_LENGTH,
) -> list[str]:
    """Formatea *payload* segun *fields* como lineas ``"Etiqueta: valor"``.

    Los campos ausentes, nulos o con el valor centinela ``"N/A"`` se muestran
    como ``N/A`` en lugar de lanzar una excepcion. Este helper es lo que
    sustituye a los 9 bloques ``try/except`` de la version original.
    """
    lines: list[str] = []
    for path, label in fields:
        value = resolve_field(payload, path)
        text = EMPTY_VALUE if value == NOT_AVAILABLE else _strip_html(str(value))
        text = _truncate(text, max_length)
        lines.append(f"{label}: {text or NOT_AVAILABLE}")
    return lines


# --------------------------------------------------------------------------
# Fichas
# --------------------------------------------------------------------------
def render_movie(movie: Any | None) -> list[str]:
    """Lineas de una pelicula. ``None`` produce un aviso.

    Acepta un :class:`~models.movie.Movie` o el payload crudo: usa
    ``raw`` cuando existe, de modo que la salida es identica en ambos casos.
    """
    if movie is None:
        return [render_separator(), "No se encontro la pelicula", render_separator()]
    payload = getattr(movie, "raw", movie)
    return [
        render_separator(),
        *render_fields(payload, OMDB_MOVIE_FIELDS),
        render_separator(),
    ]


def render_series(series: Any | None) -> list[str]:
    """Lineas del detalle de una serie.

    Acepta un :class:`~models.series.Series` (ya desenvuelto) o el envoltorio
    crudo ``{"show": {...}}``: ``_show_payload`` normaliza ambos casos.
    """
    if series is None:
        return [render_separator(), "No se encontro la serie", render_separator()]
    show = _show_payload(series)
    return [
        render_separator(),
        *render_fields(show, TVMAZE_SHOW_FIELDS),
        render_separator(),
    ]


def render_movie_stub(movie: LocalMovie) -> str:
    """Linea de una pelicula del catalogo local."""
    return f"{movie.title} ({movie.year}) - {movie.rating}"


# --------------------------------------------------------------------------
# Listados
# --------------------------------------------------------------------------
def _numbered_line(item: Mapping[str, Any], index: int) -> str:
    """Formatea un item heterogeneo del catalogo.

    Acepta las dos formas que conviven en el dominio: ficha de OMDb
    (``"Title"``/``"Year"``) y entrada local (``"titulo"``/``"anio"``). Antes
    cada uno de los tres bucles de listado del original repetia esta logica con
    su propia variante de claves.
    """
    prefix = f"{index}. "

    local_title = item.get(LOCAL_MOVIE_KEY)
    if isinstance(local_title, str) and local_title:
        rating = item.get("rating")
        suffix = f" - {rating}" if rating is not None else EMPTY_VALUE
        return f"{prefix}{local_title} ({item.get('anio', EMPTY_VALUE)}){suffix}"

    omdb_title = item.get(OMDB_MOVIE_KEY)
    if isinstance(omdb_title, str) and omdb_title:
        year = item.get("Year") or NOT_AVAILABLE
        return f"{prefix}{omdb_title} ({year})"

    return f"{prefix}Elemento desconocido"


def _payload_of(item: Any) -> Mapping[str, Any]:
    """Devuelve el payload de un item que puede ser modelo o diccionario."""
    return getattr(item, "raw", item)


def _show_payload(item: Any) -> Mapping[str, Any]:
    """Devuelve el show de un resultado, sea modelo o envoltorio crudo.

    ``Series.from_payload`` ya desenvuelve, asi que ``extract_show`` no hace
    nada en ese caso (es idempotente); si el item llega como el envoltorio
    ``{"show": {...}}`` crudo, lo desenvuelve.
    """
    return extract_show(_payload_of(item))


def render_local_movies(movies: Iterable[LocalMovie]) -> list[str]:
    """Lista numerada del catalogo local."""
    items = list(movies)
    if not items:
        return ["No se encontraron peliculas"]
    return [f"{n}. {render_movie_stub(movie)}" for n, movie in enumerate(items, start=1)]


def render_omdb_movies(movies: Iterable[Any]) -> list[str]:
    """Lista numerada de peliculas de OMDb.

    Acepta :class:`~models.movie.Movie` o el diccionario crudo.
    """
    items = [_payload_of(m) for m in movies]
    if not items:
        return ["No se encontraron peliculas"]
    return [_numbered_line(movie, n) for n, movie in enumerate(items, start=1)]


def render_series_results(results: Iterable[Any]) -> list[str]:
    """Lista numerada de resultados de busqueda de series.

    Acepta :class:`~models.series.Series` o el envoltorio crudo: en el primer
    caso el show ya viene desenvuelto, en el segundo se desenvuelve aqui.
    """
    lines: list[str] = []
    items = list(results)
    if not items:
        return ["No se encontraron series"]
    for n, result in enumerate(items, start=1):
        show = _show_payload(result)
        name = resolve_field(show, "name", EMPTY_VALUE)
        status = resolve_field(show, "status", EMPTY_VALUE)
        lines.append(f"{n}. {name} ({status})")
    return lines


def render_favorites(favorites: Iterable[Any]) -> list[str]:
    """Lista numerada de favoritas."""
    items = list(favorites)
    if not items:
        return ["No tienes peliculas favoritas"]
    return [_numbered_line(movie, n) for n, movie in enumerate(items, start=1)]


def render_history(history: Iterable[Any]) -> list[str]:
    """Lista numerada del historial."""
    items = list(history)
    if not items:
        return ["No hay historial"]
    return [
        f"{n}. {entry.title} - {entry.searched_at.strftime('%Y-%m-%d %H:%M:%S')}"
        for n, entry in enumerate(items, start=1)
    ]


# --------------------------------------------------------------------------
# Salida
# --------------------------------------------------------------------------
def print_lines(lines: Iterable[str]) -> None:
    """Imprime un bloque de lineas ya formateado."""
    for line in lines:
        print(line)


# --------------------------------------------------------------------------
# Mensajes de salida de la aplicacion
#
# Los emite el punto de entrada cuando la sesion no llega a construirse, o
# termina. Viven aqui y no en ``main.py`` para que toda la salida por pantalla
# pase por la capa de presentacion, tal como establecio la FASE 3.
# --------------------------------------------------------------------------
def show_config_error(exc: Exception) -> None:
    """La configuracion no se pudo resolver."""
    print(f"Error de configuracion: {exc}")


def show_startup_error(exc: Exception) -> None:
    """Los servicios no se pudieron construir."""
    print(f"Error de inicializacion: {exc}")


def show_cancelled() -> None:
    """El usuario cerro la entrada estandar (Ctrl+D) o cancelo."""
    print("\nPrograma cerrado.")


def show_data_error(exc: Exception) -> None:
    """Un archivo de la biblioteca esta danado o no se puede usar."""
    print(f"\nError de datos: {exc}")


def show_communication_error(exc: Exception) -> None:
    """Fallo de red irreparable en el bucle principal."""
    print(f"\nError de comunicacion: {exc}")


def show_interrupted() -> None:
    """El usuario pulso Ctrl+C."""
    print("\n\nPrograma interrumpido.")