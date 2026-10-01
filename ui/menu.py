"""Menu de consola: entrada del usuario y acciones.

Este modulo concentra las tres cosas que la anterior tenian juntas en
``main.py``: mostrar el menu, leer la entrada y ejecutar cada opcion.

Reparto:

* El **formateo** vive en :mod:`ui.display`; aqui solo se llama.
* La **logica de negocio** vive en :mod:`services`; aqui no se toca, solo se
  Coordina.
* La **entrada** (``input()``) ocurre unicamente en :func:`_prompt`.

Ningun modulo de este paquete importa a otro que lo cercle: ``menu`` importa a
``display``, nunca al reves. Por eso :func:`render_menu` vive aqui y no en
``display``: depende de :data:`MENU`, que es de este modulo.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from config import MAX_CACHE_TTL_SECONDS, MAX_TIMEOUT_INPUT, AppConfig
from constants import (
    EXIT_OPTION,
    EXIT_SUCCESS,
    FIRST_LIST_OPTION,
    OMDB_MOVIE_KEY,
)
from exceptions import (
    ApiAuthError,
    ApiError,
    EmptyQueryError,
    StorageError,
    UserCancelledError,
)
from library import movie_title
from session import Session
from utils.validators import validate_filename, validate_search_term
from ui.display import (
    print_lines,
    render_favorites,
    render_header,
    render_history,
    render_local_movies,
    render_movie,
    render_omdb_movies,
    render_series,
    render_series_results,
)

logger = logging.getLogger("peliculas.ui")

MenuAction = Callable[[Session], AppConfig | None]


# ==========================================================================
# Entrada de usuario
# ==========================================================================
def _prompt(message: str) -> str:
    """Lee una linea. Traduce ``Ctrl+C`` y ``Ctrl+D`` a excepcion de dominio.

    Antes, un ``Ctrl+C`` durante un ``input`` caia en uno de los 24
    ``except:`` desnudos y el programa continuaba como si nada.
    """
    try:
        return input(message).strip()
    except EOFError as exc:
        raise UserCancelledError("entrada finalizada (EOF)") from exc


def _ask_text(message: str) -> str:
    """Lee texto y reintenta hasta que no este vacio."""
    while True:
        value = _prompt(message)
        if value:
            return value
        print("El valor no puede estar vacio. Intente de nuevo.")


def _ask_search(message: str, field: str) -> str:
    """Lee un termino de busqueda y reintenta hasta que sea valido.

    Aplica el tope de longitud y rechaza caracteres de control. Antes solo se
    comprobaba que no estuviera vacio, de modo que un titulo de miles de
    caracteres llegaba entero a la API.
    """
    while True:
        value = _prompt(message)
        try:
            return validate_search_term(value, field=field)
        except (EmptyQueryError, TypeError) as exc:
            print(f"{exc}. Intente de nuevo.")


def _ask_filename(message: str) -> str | None:
    """Lee un nombre de archivo, reintentando, y devuelve el nombre ya validado.

    Devuelve ``None`` si la persona cancela con Enter. Rechaza separadores de
    ruta y ``..``: sin esto, escribir ``../../x`` en el menu de exportacion
    crearia directorios y escribiria fuera del directorio de trabajo.
    """
    while True:
        value = _prompt(message)
        if not value:
            return None
        try:
            return validate_filename(value)
        except (EmptyQueryError, TypeError) as exc:
            print(f"{exc}. Intente de nuevo.")


def _ask_int(message: str, *, low: int, high: int) -> int | None:
    """Lee un entero dentro de ``[low, high]``. ``None`` si el usuario cancela.

    El original hacia ``int(input(...))`` sin proteger el ``ValueError``, que
    abortaba el programa entero.
    """
    while True:
        raw = _prompt(message)
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            print(f"'{raw}' no es un numero valido. Intente de nuevo.")
            continue
        if not low <= value <= high:
            print(f"El valor debe estar entre {low} y {high}. Intente de nuevo.")
            continue
        return value


def _ask_yes_no(message: str, *, default: bool = False) -> bool:
    """Pregunta si/no. Una entrada vacia aplica *default*."""
    hint = "S/n" if default else "s/n"
    while True:
        raw = _prompt(f"{message} ({hint}): ").casefold()
        if not raw:
            return default
        if raw in {"s", "si", "y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Responda 's' o 'n'.")


def _pause() -> None:
    """Espera a que el usuario continue. Ya no usa ``delay(1)``."""
    _prompt("\nPresione Enter para continuar...")


def _clear_screen() -> None:
    """Limpia la consola de forma portable."""
    os.system("cls" if os.name == "nt" else "clear")


# ==========================================================================
# Acciones
#
# Una accion recibe la sesion completa y devuelve ``None``, o una
# ``AppConfig`` nueva si pide reconstruir la sesion. Ninguna depende de estado
# global y ninguna muta la sesion que recibe.
# ==========================================================================
def _report_api_error(prefix: str, exc: ApiError) -> None:
    """Registra la traza completa y muestra al usuario un mensaje segun la causa.

    Se centraliza aqui para no repetir el mismo ``except ApiAuthError`` en las
    cinco acciones que consultan una API.

    * ``logger.exception`` (y no ``warning``) porque adjunta el traceback: sin
      el, el log solo decia "fallo" sin indicar por que.
    * Un 401/403 no se arregla reintentando, asi que el mensaje sugiere revisar
      ``OMDB_API_KEY`` en lugar de repetir la misma consulta.
    """
    logger.exception("fallo en la consulta: %s", prefix)
    if isinstance(exc, ApiAuthError):
        print(f"{prefix}: la API rechazo la credencial; revisa OMDB_API_KEY. Detalle: {exc}")
    else:
        print(f"{prefix}: {exc}")


def accion_buscar_pelicula(session: Session) -> AppConfig | None:
    """Opcion 1: buscar una pelicula por titulo."""
    title = _ask_search("Ingrese el titulo de la pelicula: ", "el titulo")

    try:
        movie = session.movies.search_movie(title)
    except ApiError as exc:
        _report_api_error("No se pudo consultar el servicio de peliculas", exc)
        _pause()
        return None

    if movie is None:
        print_lines(render_movie(None))
        _pause()
        return None

    print_lines(render_movie(movie))
    session.library.add_to_history(movie.raw)

    if _ask_yes_no("\n¿Agregar a favoritos?", default=False):
        if session.library.add_favorite(movie.raw):
            print("Agregada a favoritos.")
        else:
            print("Ya estaba en favoritos.")

    _pause()
    return None


def accion_buscar_actor(session: Session) -> AppConfig | None:
    """Opcion 2: buscar peliculas por actor."""
    actor = _ask_search("Ingrese el nombre del actor: ", "el nombre del actor")

    try:
        movies = session.movies.movies_by_actor(actor)
    except ApiError as exc:
        _report_api_error("No se pudo consultar el servicio de peliculas", exc)
        _pause()
        return None

    if not movies:
        print(f"No se encontraron peliculas para {actor}.")
        _pause()
        return None

    print(f"Se encontraron {len(movies)} peliculas:")
    print_lines(render_omdb_movies(movies))

    index = _ask_int(
        "\nPelicula a ver en detalle (Enter para volver): ",
        low=FIRST_LIST_OPTION,
        high=len(movies),
    )
    if index is not None:
        selected_title = movies[index - 1].raw.get(OMDB_MOVIE_KEY)
        if not selected_title:
            print("Ese resultado no tiene titulo legible.")
            _pause()
            return None
        try:
            detail = session.movies.search_movie(str(selected_title))
        except ApiError as exc:
            _report_api_error("No se pudo consultar el detalle", exc)
        else:
            print_lines(render_movie(detail))

    _pause()
    return None


def accion_buscar_series(session: Session) -> AppConfig | None:
    """Opcion 3: buscar series."""
    name = _ask_search("Ingrese el nombre de la serie: ", "el nombre de la serie")

    try:
        results = session.series.search_series(name)
    except ApiError as exc:
        _report_api_error("No se pudo consultar el servicio de series", exc)
        _pause()
        return None

    if not results:
        print(f"No se encontraron series para {name}.")
        _pause()
        return None

    print(f"Se encontraron {len(results)} series:")
    print_lines(render_series_results(results))

    index = _ask_int(
        "\nSerie a ver en detalle (Enter para volver): ",
        low=FIRST_LIST_OPTION,
        high=len(results),
    )
    if index is not None:
        show_id = results[index - 1].id
        if show_id is None:
            print("Esa serie no trae identificador, no se puede pedir su detalle.")
            _pause()
            return None
        try:
            detail = session.series.series_details(show_id)
        except ApiError as exc:
            _report_api_error("No se pudo consultar el detalle", exc)
        else:
            print_lines(render_series(detail))

    _pause()
    return None


def accion_peliculas_populares(session: Session) -> AppConfig | None:
    """Opcion 4: catalogo local de populares. No hace peticiones de red."""
    print_lines(render_header("PELICULAS POPULARES"))
    print_lines(render_local_movies(session.movies.popular_movies()))
    _pause()
    return None


def accion_buscar_por_genero(session: Session) -> AppConfig | None:
    """Opcion 5: catalogo local por genero. No hace peticiones de red."""
    genres = session.movies.available_genres()
    print(f"Generos disponibles: {', '.join(genres)}")
    genre = _ask_search("Ingrese el genero: ", "el genero")

    print_lines(render_local_movies(session.movies.movies_by_genre(genre)))
    _pause()
    return None


def accion_ver_favoritas(session: Session) -> AppConfig | None:
    """Opcion 6: listar y eliminar favoritas."""
    print_lines(render_header("MIS FAVORITOS"))
    favorites = session.library.favorites
    print_lines(render_favorites(favorites))

    if favorites:
        index = _ask_int(
            "\n¿Eliminar alguna? (Enter para volver): ",
            low=FIRST_LIST_OPTION,
            high=len(favorites),
        )
        if index is not None:
            title = movie_title(favorites[index - 1])
            if session.library.remove_favorite(title):
                print("Eliminada de favoritos.")
            else:
                print("No se pudo eliminar.")

    _pause()
    return None


def accion_ver_historial(session: Session) -> AppConfig | None:
    """Opcion 7: listar y limpiar el historial."""
    print_lines(render_header("HISTORIAL DE BUSQUEDAS"))
    print_lines(render_history(session.library.history))

    if session.library.history and _ask_yes_no("\n¿Limpiar historial?", default=False):
        session.library.clear_history()
        print("Historial limpiado.")

    _pause()
    return None


def accion_estadisticas(session: Session) -> AppConfig | None:
    """Opcion 8: contadores de la biblioteca y metricas de cache."""
    stats = session.library.statistics()
    print_lines(render_header("ESTADISTICAS"))
    print(f"Total favoritas     : {stats.total_favorites}")
    print(f"Total historial     : {stats.total_history}")
    if stats.favorites_with_rating is not None:
        print(f"Rating medio (fav.) : {stats.favorites_with_rating:.2f}")

    caches = session.cache_stats()
    print("Cache:")
    for name, metrics in caches.items():
        print(
            f"  {name:<7} entradas={metrics['entries']:<4} "
            f"aciertos={metrics['hits']:<4} ratio={metrics['hit_rate']:.2%}"
        )
    logger.debug("metricas de cache: %s", caches)

    _pause()
    return None


def accion_exportar(session: Session) -> AppConfig | None:
    """Opcion 9: exportar la biblioteca a JSON."""
    name = _ask_filename("Nombre del archivo (sin extension): ")
    if name is None:
        return None
    try:
        written = session.library.export_to_json(name)
    except StorageError as exc:
        logger.error("fallo al exportar: %s", exc)
        print(f"No se pudo exportar: {exc}")
    except EmptyQueryError as exc:
        # Barrera de la interfaz: la biblioteca vuelve a validar, pero aqui el
        # mensaje es util para la persona y no una traza de excepcion.
        logger.warning("nombre de archivo rechazado: %s", exc)
        print(f"Nombre de archivo no valido: {exc}")
    else:
        print(f"Exportado a {written}")

    _pause()
    return None


def accion_importar(session: Session) -> AppConfig | None:
    """Opcion 10: importar la biblioteca desde JSON."""
    name = _ask_filename("Nombre del archivo (sin extension): ")
    if name is None:
        return None
    try:
        favorites, history = session.library.import_from_json(name)
    except StorageError as exc:
        # El original usaba un ``except:`` que ademas capturaba Ctrl+C.
        logger.error("fallo al importar %s: %s", name, exc)
        print(f"Error al importar '{name}': {exc}")
    except EmptyQueryError as exc:
        logger.warning("nombre de archivo rechazado: %s", exc)
        print(f"Nombre de archivo no valido: {exc}")
    else:
        print(f"Importado desde {name}: {favorites} favoritas, {history} de historial.")

    _pause()
    return None


# --------------------------------------------------------------------------
# Opciones del menu de configuracion
# --------------------------------------------------------------------------
def _toggle_debug(config: AppConfig) -> AppConfig:
    updated = config.with_flags(debug=not config.debug)
    print(f"Debug ahora es: {updated.debug}")
    return updated


def _toggle_verbose(config: AppConfig) -> AppConfig:
    updated = config.with_flags(verbose=not config.verbose)
    print(f"Verbose ahora es: {updated.verbose}")
    return updated


def _change_timeout(config: AppConfig) -> AppConfig:
    seconds = _ask_int(
        "Nuevo timeout en segundos: ", low=FIRST_LIST_OPTION, high=MAX_TIMEOUT_INPUT
    )
    if seconds is None:
        return config
    updated = config.with_timeout(float(seconds))
    print(f"Timeout ahora es: {updated.request_timeout} s")
    return updated


def _change_cache_ttl(config: AppConfig) -> AppConfig:
    seconds = _ask_int(
        "Nuevo TTL de cache en segundos: ",
        low=FIRST_LIST_OPTION,
        high=MAX_CACHE_TTL_SECONDS,
    )
    if seconds is None:
        return config
    updated = config.with_overrides(cache_ttl_seconds=seconds)
    print(f"TTL de cache ahora es: {updated.cache_ttl_seconds} s")
    return updated


def _change_api_key(config: AppConfig) -> AppConfig:
    key = _ask_search("Nueva OMDB API key: ", "la API key")
    updated = config.with_overrides(omdb_api_key=key)
    print("API key actualizada para esta sesion.")
    return updated


#: Tabla de las opciones del menu de configuracion.
#:
#: Antes el rango valido (``high=5`` en ``accion_configuracion``) y los casos que
#: ``_apply_config_change`` resolvia (``if option == 1 ... 5``) estaban escritos
#: por separado, de modo que anadir una opcion 6 la haria aceptable por el menu
#: pero inalcanzable, sin ningun error. Al haber una unica tabla, ambos hechos
#: se derivan de ella y no pueden divergir.
_CONFIG_HANDLERS: dict[int, Callable[[AppConfig], AppConfig]] = {
    1: _toggle_debug,
    2: _toggle_verbose,
    3: _change_timeout,
    4: _change_cache_ttl,
    5: _change_api_key,
}

#: Numero de opciones del menu de configuracion. El menu ofrece ademas la 0
#: ("volver"), que cancela, de ahi que el rango valide de 0 a este valor.
MAX_CONFIG_OPTION: int = max(_CONFIG_HANDLERS)


def accion_configuracion(session: Session) -> AppConfig | None:
    """Opcion 11: consultar y ajustar la configuracion.

    Devuelve la configuracion nueva para que el bucle reconstruya la sesion.
    No muta nada compartido: construye otro ``AppConfig``. Es la diferencia
    clave frente al original, que hacia ``CONFIG["timeout"] =
    int(input(...))`` sobre el diccionario de otro modulo.
    """
    print_lines(render_header("CONFIGURACION"))
    config = session.config

    print(f"1. Debug    : {config.debug}")
    print(f"2. Verbose  : {config.verbose}")
    print(f"3. Timeout  : {config.request_timeout} s")
    print(f"4. TTL cache: {config.cache_ttl_seconds} s")
    print("5. API key  : definida (valor no mostrado)")

    warnings = config.validate()
    if warnings:
        print("\nAvisos de configuracion:")
        for warning in warnings:
            print(f"  - {warning}")

    option = _ask_int(
        "\nOpcion a cambiar (0 para volver): ", low=0, high=MAX_CONFIG_OPTION
    )
    if option is None or option == 0:
        _pause()
        return None

    updated = _apply_config_change(config, option)
    if updated is config:
        _pause()
        return None

    print("Cambio aplicado: los servicios se reconstruyen con la nueva configuracion.")
    _pause()
    return updated


def _apply_config_change(config: AppConfig, option: int) -> AppConfig:
    """Devuelve una configuracion nueva segun la opcion elegida.

    Despacha sobre :data:`_CONFIG_HANDLERS`. Una opcion desconocida devuelve
    *config* sin cambios, en lugar de caer en un ``None`` implicito.
    """
    handler = _CONFIG_HANDLERS.get(option)
    if handler is None:
        logger.debug("opcion de configuracion desconocida: %r", option)
        return config
    return handler(config)


# ==========================================================================
# Menu
# ==========================================================================
#: Tabla del menu. Sustituye a la cadena de 12 ramas ``if/elif`` del original.
MENU: tuple[tuple[int, str, MenuAction], ...] = (
    (1, "Buscar pelicula por titulo", accion_buscar_pelicula),
    (2, "Buscar por actor", accion_buscar_actor),
    (3, "Buscar series", accion_buscar_series),
    (4, "Ver peliculas populares", accion_peliculas_populares),
    (5, "Buscar por genero", accion_buscar_por_genero),
    (6, "Ver favoritos", accion_ver_favoritas),
    (7, "Ver historial", accion_ver_historial),
    (8, "Ver estadisticas", accion_estadisticas),
    (9, "Exportar datos", accion_exportar),
    (10, "Importar datos", accion_importar),
    (11, "Configuracion", accion_configuracion),
)

_OPTIONS_BY_NUMBER: dict[int, MenuAction] = {n: action for n, _label, action in MENU}


def render_menu() -> list[str]:
    """Lineas del menu principal, incluida la opcion de salida."""
    lines = render_header("SISTEMA DE PELICULAS Y SERIES")
    for option, label, _action in MENU:
        lines.append(f"{option:>2}. {label}")
    lines.append(f"{EXIT_OPTION:>2}. Salir")
    return lines


def run_menu(session: Session) -> int:
    """Repite el menu hasta que el usuario salga o cancele.

    Si una accion devuelve una ``AppConfig`` (solo la de configuracion), se
    reconstruye la sesion con ella.
    """
    current = session
    try:
        while True:
            _clear_screen()
            print_lines(render_menu())

            option = _ask_int("Seleccione una opcion: ", low=0, high=EXIT_OPTION)
            if option is None:
                print("Opcion no valida.")
                continue
            if option == EXIT_OPTION:
                print("¡Hasta luego!")
                return EXIT_SUCCESS

            action = _OPTIONS_BY_NUMBER.get(option)
            if action is None:
                print("Opcion no valida.")
                continue

            new_config = action(current)
            if new_config is not None:
                current = current.rebuild_with(new_config)
    finally:
        current.close()


__all__ = [
    "MENU",
    "MAX_CONFIG_OPTION",
    "accion_buscar_actor",
    "accion_buscar_pelicula",
    "accion_buscar_por_genero",
    "accion_buscar_series",
    "accion_configuracion",
    "accion_estadisticas",
    "accion_exportar",
    "accion_importar",
    "accion_peliculas_populares",
    "accion_ver_favoritas",
    "accion_ver_historial",
    "render_menu",
    "run_menu",
]