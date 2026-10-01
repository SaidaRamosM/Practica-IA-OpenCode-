"""Pruebas de :mod:`ui.display`: el formateo a lineas de texto.

Este modulo tiene una regla que lo hace testeable sin capturar ``stdout``: las
funciones ``render_*`` **devuelven** listas de lineas, y solo ``print_lines`` y
los ``show_*`` imprimen. Por eso casi todo lo de aqui se puede comprobar
inspeccionando el valor devuelto.

Lo que se fija:

* la tabla de campos de ``constants`` es la unica fuente del formato, asi que
  cada campo declarado tiene que salir en pantalla;
* los valores ausentes se muestran como ``N/A`` y no como ``None`` ni vacio;
* los resumenes largos se recortan, que es lo que evita que una serie con un
  parrafo entero desborde la consola;
* el HTML de TVMaze se limpia antes de imprimirse, porque si no la persona ve
  las etiquetas.

No se prueba ``ui/menu``: es el modulo con ``input()`` y su logica de validacion
ya esta cubierta en ``test_validators.py`` y ``test_library.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from constants import (
    NOT_AVAILABLE,
    OMDB_MOVIE_FIELDS,
    SEPARATOR_CHAR,
    SEPARATOR_WIDTH,
    SUMMARY_MAX_LENGTH,
    TVMAZE_SHOW_FIELDS,
    LocalMovie,
)
from models.movie import Movie
from models.series import Series
from ui import display


class TestRenderSeparator:
    """La linea horizontal de la cabecera."""

    def test_usa_el_caracter_y_el_ancho_por_defecto(self) -> None:
        separador = display.render_separator()

        assert separador == SEPARATOR_CHAR * SEPARATOR_WIDTH

    def test_admite_caracter_y_ancho_propios(self) -> None:
        assert display.render_separator("-", width=10) == "-" * 10

    def test_es_una_sola_linea(self) -> None:
        assert "\n" not in display.render_separator()


class TestRenderHeader:
    def test_rodea_el_texto_con_separadores(self) -> None:
        lineas = display.render_header("PELICULAS")

        assert lineas[0].startswith(SEPARATOR_CHAR)
        assert "PELICULAS" in lineas[1]
        assert lineas[2].startswith(SEPARATOR_CHAR)

    def test_el_ancho_se_puede_ajustar(self) -> None:
        lineas = display.render_header("X", width=20)

        assert len(lineas[0]) == 20

    def test_devuelve_tres_lineas(self) -> None:
        assert len(display.render_header("X")) == 3


class TestRenderFields:
    """La tabla que imprime peliculas y series."""

    def test_una_linea_por_campo(self) -> None:
        # El formato sale de `constants`, no de un `try/except` por campo.
        lineas = display.render_fields(
            {"Title": "Interstellar", "Year": "2014"}, OMDB_MOVIE_FIELDS
        )

        assert len(lineas) == len(OMDB_MOVIE_FIELDS)

    def test_usa_la_etiqueta_local_de_cada_campo(self) -> None:
        lineas = display.render_fields({"Title": "Interstellar"}, OMDB_MOVIE_FIELDS)

        assert any("Titulo" in linea for linea in lineas)

    def test_muestra_el_valor_que_Le_corresponde(self) -> None:
        lineas = display.render_fields(
            {"Title": "Interstellar", "Year": "2014"}, OMDB_MOVIE_FIELDS
        )

        assert any("Interstellar" in linea and "Titulo" in linea for linea in lineas)
        assert any("2014" in linea and "Anio" in linea for linea in lineas)

    def test_un_campo_ausente_se_muestra_como_n_a(self) -> None:
        # N/A y no "" ni "None": un hueco en la tabla no se distingue de un
        # dato vacio si se deja en blanco.
        lineas = display.render_fields({"Title": "X"}, OMDB_MOVIE_FIELDS)

        assert any(NOT_AVAILABLE in linea for linea in lineas)

    def test_lee_una_ruta_anidada(self) -> None:
        lineas = display.render_fields(
            {"rating": {"average": 9.3}}, (("rating.average", "Rating"),)
        )

        assert "9.3" in lineas[0]

    def test_una_ruta_anidada_rota_no_rompe(self) -> None:
        # TVMaze omite `rating` en series sin puntuacion. La tabla tiene que
        # seguir saliendo entera, con esa celda a N/A.
        lineas = display.render_fields({}, TVMAZE_SHOW_FIELDS)

        assert len(lineas) == len(TVMAZE_SHOW_FIELDS)

    def test_el_tope_de_longitud_recorta_los_valores_largos(self) -> None:
        # El detalle de una serie puede traer un parrafo entero: sin recorte,
        # la ficha no cabe en la pantalla.
        largo = "x" * (SUMMARY_MAX_LENGTH + 100)

        lineas = display.render_fields(
            {"Plot": largo}, (("Plot", "Trama"),), max_length=50
        )

        assert len(lineas[0]) < len(largo)

    def test_un_valor_corto_no_se_toca(self) -> None:
        lineas = display.render_fields(
            {"Plot": "Corto"}, (("Plot", "Trama"),), max_length=50
        )

        assert "Corto" in lineas[0]

    def test_acepta_campos_vacios(self) -> None:
        assert display.render_fields({"a": 1}, ()) == []


class TestRenderMovie:
    """La ficha completa de una pelicula."""

    def test_rodea_la_tabla_con_separadores(
        self, movie: Movie
    ) -> None:
        # La ficha son los dos separadores mas una linea por campo. Los
        # separadores son los que encierran el bloque en pantalla.
        lineas = display.render_movie(movie)

        assert lineas[0] == SEPARATOR_CHAR * SEPARATOR_WIDTH
        assert lineas[-1] == SEPARATOR_CHAR * SEPARATOR_WIDTH
        assert len(lineas) == len(OMDB_MOVIE_FIELDS) + 2

    def test_incluye_el_titulo(self, movie: Movie) -> None:
        assert any("Interstellar" in linea for linea in display.render_movie(movie))

    def test_acepta_un_dict_sin_pasarlo_por_modelo(
        self, omdb_pelicula_encontrada: Mapping[str, Any]
    ) -> None:
        # La presentacion acepta cualquiera de los dos: el menu guarda en
        # favoritas el dict crudo, no el modelo.
        lineas = display.render_movie(dict(omdb_pelicula_encontrada))

        assert any("Interstellar" in linea for linea in lineas)

    def test_acepta_none_sin_reventar(
        self,
    ) -> None:
        # `render_movie(None)` se usa para el hueco de una busqueda vacia.
        lineas = display.render_movie(None)

        assert isinstance(lineas, list)

    def test_todos_los_campos_de_la_tabla_salen_alguna_vez(
        self, omdb_pelicula_encontrada: Mapping[str, Any]
    ) -> None:
        # La garantia de que la tabla de `constants` y la pantalla estan
        # sincronizadas: si alguien anade un campo a la tupla y olvida la
        # etiqueta, este test lo nota.
        lineas = "\n".join(display.render_movie(Movie.from_payload(omdb_pelicula_encontrada)))

        for _clave, etiqueta in OMDB_MOVIE_FIELDS:
            assert etiqueta in lineas, f"falta la etiqueta {etiqueta!r}"


class TestRenderSeries:
    """La ficha de una serie, con la anidacion de TVMaze."""

    def test_rodea_la_tabla_con_separadores(
        self, series: Series
    ) -> None:
        lineas = display.render_series(series)

        assert lineas[0] == SEPARATOR_CHAR * SEPARATOR_WIDTH
        assert lineas[-1] == SEPARATOR_CHAR * SEPARATOR_WIDTH
        assert len(lineas) == len(TVMAZE_SHOW_FIELDS) + 2

    def test_muestra_el_nombre(self, series: Series) -> None:
        assert any("Breaking Bad" in linea for linea in display.render_series(series))

    def test_muestra_el_rating_anidado(
        self, series: Series
    ) -> None:
        # "rating.average" es la razon de la notacion con puntos.
        assert any("9.3" in linea for linea in display.render_series(series))

    def test_limpia_el_html_del_resumen(
        self, series: Series
    ) -> None:
        # TVMaze devuelve `<p>...`. Sin limpiarlo, la persona ve las etiquetas
        # en pantalla. Aqui se comprueba que desaparecen.
        lineas = "\n".join(display.render_series(series))

        assert "<p>" not in lineas
        assert "</p>" not in lineas

    def test_conserva_el_texto_del_resumen(
        self, series: Series
    ) -> None:
        # Limpiar no es borrar: el texto tiene que seguir ahi.
        lineas = "\n".join(display.render_series(series))

        assert "metanfetamina" in lineas

    def test_acepta_none_sin_reventar(self) -> None:
        assert isinstance(display.render_series(None), list)

    def test_todas_las_etiquetas_de_la_tabla_salen(
        self, series: Series
    ) -> None:
        lineas = "\n".join(display.render_series(series))

        for _clave, etiqueta in TVMAZE_SHOW_FIELDS:
            assert etiqueta in lineas


class TestRenderListados:
    """Los listados: locales, de OMDb y de series."""

    def test_las_peliculas_locales_salen_como_tabla(
        self,
    ) -> None:
        movies = (
            LocalMovie("The Shawshank Redemption", 1994, 9.3),
            LocalMovie("The Godfather", 1972, 9.2),
        )

        lineas = display.render_local_movies(movies)

        assert any("The Shawshank Redemption" in linea for linea in lineas)
        assert any("9.3" in linea for linea in lineas)

    def test_un_listado_local_vacio_avisa(
        self,
    ) -> None:
        # Un mensaje, no un hueco: si no, la pantalla queda sin explicar nada.
        lineas = display.render_local_movies(())

        assert lineas
        assert any(linea.strip() for linea in lineas)

    def test_los_generos_que_genera_local_movies_estan_vinculados(
        self,
    ) -> None:
        from constants import GENRE_LABELS, MOVIES_BY_GENRE

        for genero in GENRE_LABELS:
            assert genero in MOVIES_BY_GENRE

    def test_las_peliculas_de_omdb_salen_con_su_id(
        self, omdb_pelicula_encontrada: Mapping[str, Any]
    ) -> None:
        # El menu pide elegir por indice, asi que la posicion importa y la
        # lista tiene que ser numerada.
        movies = [Movie.from_payload(omdb_pelicula_encontrada)]

        lineas = display.render_omdb_movies(movies)

        assert any("Interstellar" in linea for linea in lineas)
        assert any("1" in linea for linea in lineas)

    def test_un_listado_de_omdb_vacio_avisa(self) -> None:
        assert display.render_omdb_movies(())

    def test_los_stubs_locales_son_una_sola_linea(
        self,
    ) -> None:
        # `render_movie_stub` es la version de una linea del catalogo local.
        stub = display.render_movie_stub(LocalMovie("The Godfather", 1972, 9.2))

        assert isinstance(stub, str)
        assert "\n" not in stub
        assert "The Godfather" in stub

    def test_los_stubs_estan_numerados_para_poder_elegir(
        self,
    ) -> None:
        lineas = display.render_local_movies(
            (LocalMovie("A", 2000, 8.0), LocalMovie("B", 2001, 8.1))
        )

        # Numeracion desde 1: el 0 esta reservado para "volver".
        assert any(linea.strip().startswith("1") for linea in lineas)
        assert any(linea.strip().startswith("2") for linea in lineas)

    def test_los_resultados_de_series_salen_desenvueltos(
        self, tvmaze_busqueda: list[dict[str, Any]]
    ) -> None:
        # La lista viene con envoltorio `{"show": {...}}`: la pantalla tiene que
        # mostrar el nombre de la serie, no un volcado del envoltorio.
        lineas = display.render_series_results(
            [Series.from_payload(p) for p in tvmaze_busqueda]
        )

        assert any("Breaking Bad" in linea for linea in lineas)

    def test_las_favoritas_se_muestran_con_su_titulo(
        self, omdb_pelicula_encontrada: Mapping[str, Any]
    ) -> None:
        lineas = display.render_favorites([dict(omdb_pelicula_encontrada)])

        assert any("Interstellar" in linea for linea in lineas)

    def test_sin_favoritas_avisa(self) -> None:
        assert display.render_favorites(())

    def test_el_historial_se_muestra_con_su_fecha(
        self,
    ) -> None:
        from datetime import datetime, timezone

        from library import HistoryEntry

        entradas = [
            HistoryEntry(
                title="Interstellar",
                searched_at=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
            )
        ]

        lineas = display.render_history(entradas)

        assert any("Interstellar" in linea for linea in lineas)
        assert any("2026" in linea for linea in lineas)

    def test_sin_historial_avisa(self) -> None:
        assert display.render_history(())

    def test_el_historial_muestra_la_fecha_como_texto(
        self,
    ) -> None:
        # Y no el repr de un objeto datetime, que en pantalla es ilegible.
        from datetime import datetime, timezone

        from library import HistoryEntry

        lineas = "\n".join(
            display.render_history(
                [
                    HistoryEntry(
                        title="X",
                        searched_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
                    )
                ]
            )
        )

        assert "datetime(" not in lineas
        assert "tzinfo=" not in lineas


class TestMensajesDeError:
    """Los ``show_*``: el texto que ve la persona cuando algo falla."""

    def test_el_error_de_configuracion_explica_el_problema(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from exceptions import ConfigError

        display.show_config_error(
            ConfigError("falta la variable de entorno obligatoria OMDB_API_KEY")
        )

        salida = capsys.readouterr().out
        assert "OMDB_API_KEY" in salida

    def test_el_error_de_comunicacion_incluye_el_detalle(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # `show_communication_error` es generico: imprime el texto de la
        # excepcion. El consejo de revisar `OMDB_API_KEY` para un 401 lo anade
        # el menu, en `_show_query_error`, que es quien sabe si la excepcion
        # fue de credencial. Aqui se comprueba lo que este modulo hace.
        from exceptions import ApiAuthError

        display.show_communication_error(ApiAuthError("estado HTTP 401"))

        salida = capsys.readouterr().out
        assert "401" in salida
        assert "comunicacion" in salida.lower()

    def test_el_error_de_datos_incluye_el_detalle(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from exceptions import CorruptedStorageError

        display.show_data_error(CorruptedStorageError("JSON invalido en el archivo"))

        salida = capsys.readouterr().out
        assert "JSON invalido" in salida
        assert "datos" in salida.lower()

    def test_cada_tipo_de_error_tiene_su_propia_etiqueta(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # "Error de datos" y "Error de comunicacion" tienen que distinguirse:
        # uno significa "revisa tu archivo" y el otro "la red fallo", y la
        # accion que sirve es distinta.
        from exceptions import ApiError, StorageError

        display.show_data_error(StorageError("fallo"))
        datos = capsys.readouterr().out

        display.show_communication_error(ApiError("fallo"))
        comunicacion = capsys.readouterr().out

        assert "datos" in datos.lower()
        assert "comunicacion" in comunicacion.lower()

    def test_los_mensajes_no_son_vacios(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Una pantalla en blanco tras un error deja al usuario sin saber que
        # hacer.
        from exceptions import ApiError, ConfigError, StorageError

        for mostrar, error in (
            (display.show_startup_error, StorageError("fallo")),
            (display.show_communication_error, ApiError("fallo")),
            (display.show_config_error, ConfigError("fallo")),
            (display.show_data_error, StorageError("fallo")),
        ):
            mostrar(error)
            assert capsys.readouterr().out.strip()

    def test_los_mensajes_no_levantan_la_excepcion_original(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Mostrar un error no puede propagarlo: el punto de entrada ya lo capturo.
        from exceptions import ConfigError

        error = ConfigError("algo falla")

        display.show_config_error(error)

        assert capsys.readouterr().out.strip()
        assert isinstance(error, ConfigError)

    def test_cancelar_e_interrumpir_tienen_mensajes_propios(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # "Hasta luego" y "interrumpido" son situaciones distintas: una es
        # electiva y la otra no.
        display.show_cancelled()
        salida_cancelar = capsys.readouterr().out

        display.show_interrupted()
        salida_interrumpir = capsys.readouterr().out

        assert salida_cancelar.strip()
        assert salida_interrumpir.strip()
        assert salida_cancelar != salida_interrumpir


class TestConfigureOutputYLogging:
    """La configuracion de la consola, que se ejecuta una sola vez."""

    def test_configure_output_no_falla_con_una_consola_estrecha(
        self,
    ) -> None:
        # Fuerza UTF-8 con reemplazo. En una consola con la ventana de
        # codificacion antigua, un titulo con cirilico reventaba el programa.
        # Solo se comprueba que no levante: cambiar la codificacion real
        # durante los tests afectaria a pytest.
        display.configure_output()

    def test_configure_logging_acepta_los_tres_niveles(self) -> None:
        # debug > verbose > silencio. Los tres tienen que ser aceptados.
        for debug, verbose in ((True, False), (False, True), (False, False)):
            display.configure_logging(debug, verbose)

    def test_configure_logging_no_devuelve_nada(self) -> None:
        assert display.configure_logging(True, False) is None

    def test_print_lines_imprime_cada_linea(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # `print_lines` es el unico puente entre las lineas devueltas y la
        # pantalla: sin el, habria que imprimir dentro de cada `render_*`.
        display.print_lines(["primera", "segunda"])

        salida = capsys.readouterr().out
        assert "primera" in salida
        assert "segunda" in salida

    def test_print_lines_admite_un_generador(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Las vistas de la biblioteca devuelven tuplas, no listas.
        display.print_lines(linea for linea in ("a", "b"))

        assert "a" in capsys.readouterr().out

    def test_print_lines_no_acepta_una_cadena_suelta(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Comportamiento real, documentado aqui a proposito: `print_lines` itera
        # su argumento, y una cadena es iterable por caracteres. No es un fallo
        # porque todos los llamantes le pasan listas o tuplas; pero quien lo use
        # con una cadenavera "hola" en cuatro lineas, y conviene saberlo.
        display.print_lines("hola")

        salida = capsys.readouterr().out
        assert salida.splitlines() == ["h", "o", "l", "a"]
