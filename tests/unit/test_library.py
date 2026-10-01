"""Pruebas de :class:`MovieLibrary`: favoritas, historial y persistencia.

Tres cosas highlighted por el diseno de la FASE 3, y que un test ingenuo pasaria
por alto:

* las vistas (``favorites``, ``history``) son **inmutables**: quien las recibe
  no puede modificar la biblioteca por la espalda;
* el historial esta **acotado** y con fecha ISO 8601 real, no la cadena
  ``"hoy"`` del original;
* importar **valida antes de tocar el estado**: un archivo corrupto deja la
  biblioteca intacta.

Los tests que escriben en disco usan ``tmp_path``, el directorio temporal que
pytest crea por test. Nada escribe en el directorio del proyecto, asi que la
suite se puede ejecutar en paralelo sin que una prueba pise el archivo de otra.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from exceptions import CorruptedStorageError, EmptyQueryError, StorageError
from library import (
    SCHEMA_VERSION,
    HistoryEntry,
    MovieLibrary,
    movie_title,
)


@pytest.fixture
def biblioteca() -> MovieLibrary:
    """Biblioteca vacia con el historial acotado a 3 entradas."""
    return MovieLibrary(max_history_entries=3)


@pytest.fixture
def reloj_fijo() -> Any:
    """Reloj de :class:`MovieLibrary` que avanza de forma controlada."""

    class Reloj:
        def __init__(self) -> None:
            self.momento = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        def __call__(self) -> datetime:
            return self.momento

        def avanza(self, **kwargs: float) -> None:
            self.momento += timedelta(**kwargs)

    return Reloj()


@pytest.fixture
def biblioteca_con_reloj(reloj_fijo: Any) -> MovieLibrary:
    """Biblioteca cuyo historial tiene fechas deterministas."""
    return MovieLibrary(max_history_entries=3, clock=reloj_fijo)


class TestFavoritas:
    """La coleccion personal del usuario."""

    def test_agrega_una_pelicula(self, biblioteca: MovieLibrary) -> None:
        assert biblioteca.add_favorite({"Title": "Interstellar", "Year": "2014"}) is True
        assert len(biblioteca.favorites) == 1

    def test_no_agrega_dos_veces_la_misma(
        self, biblioteca: MovieLibrary
    ) -> None:
        # `add_favorite` devuelve si hizo algo, para que la interfaz pueda
        # decir "ya estaba en favoritas" en vez de anadir un duplicado.
        biblioteca.add_favorite({"Title": "Interstellar"})

        assert biblioteca.add_favorite({"Title": "Interstellar"}) is False
        assert len(biblioteca.favorites) == 1

    def test_el_titulo_se_compara_sin_distinguir_mayusculas(
        self, biblioteca: MovieLibrary
    ) -> None:
        # "Matrix" y "matrix" son la misma pelicula para la persona.
        biblioteca.add_favorite({"Title": "Matrix"})

        assert biblioteca.add_favorite({"Title": "matrix"}) is False

    def test_el_titulo_se_compara_ignorando_espacios(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_favorite({"Title": "Matrix"})

        assert biblioteca.add_favorite({"Title": "  Matrix  "}) is False

    def test_acepta_una_pelicula_del_catalogo_local(
        self, biblioteca: MovieLibrary
    ) -> None:
        # La clave local es "titulo", no "Title": ambas tienen que entrar.
        assert biblioteca.add_favorite({"titulo": "The Godfather"}) is True

    def test_guarda_una_copia_y_no_la_referencia(
        self, biblioteca: MovieLibrary
    ) -> None:
        # Si guardara la referencia, mutar el diccionario del llamador
        # cambiaria la biblioteca sin pasar por sus metodos.
        pelicula = {"Title": "Interstellar", "Year": "2014"}
        biblioteca.add_favorite(pelicula)

        pelicula["Title"] = "Otro titulo"

        assert biblioteca.favorites[0]["Title"] == "Interstellar"

    def test_elimina_por_titulo(self, biblioteca: MovieLibrary) -> None:
        biblioteca.add_favorite({"Title": "Interstellar"})

        assert biblioteca.remove_favorite("Interstellar") is True
        assert biblioteca.favorites == ()

    def test_eliminar_ignora_mayusculas(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_favorite({"Title": "Interstellar"})

        assert biblioteca.remove_favorite("INTERSTELLAR") is True

    def test_eliminar_una_pelicula_inexistente_devuelve_false(
        self, biblioteca: MovieLibrary
    ) -> None:
        assert biblioteca.remove_favorite("No existe") is False

    def test_eliminar_no_afecta_a_las_demas(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_favorite({"Title": "A"})
        biblioteca.add_favorite({"Title": "B"})

        biblioteca.remove_favorite("A")

        assert [movie_title(m) for m in biblioteca.favorites] == ["B"]

    def test_find_favorite_devuelve_la_pelicula(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_favorite({"Title": "Interstellar", "Year": "2014"})

        encontrada = biblioteca.find_favorite("interstellar")

        assert encontrada is not None
        assert encontrada["Year"] == "2014"

    def test_find_favorite_devuelve_none_si_no_existe(
        self, biblioteca: MovieLibrary
    ) -> None:
        assert biblioteca.find_favorite("No existe") is None

    def test_clear_favorites_vacia_la_coleccion(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_favorite({"Title": "A"})
        biblioteca.add_favorite({"Title": "B"})

        biblioteca.clear_favorites()

        assert biblioteca.favorites == ()

    def test_las_favoritas_no_se_pueden_modificar_por_la_vista(
        self, biblioteca: MovieLibrary
    ) -> None:
        # La vista es una tupla: no tiene `append`. Antes era la lista viva, y
        # `main.py` podia mutarla sin que la biblioteca se enterase.
        biblioteca.add_favorite({"Title": "Interstellar"})

        vista = biblioteca.favorites

        assert isinstance(vista, tuple)
        with pytest.raises(AttributeError):
            vista.append({"Title": "Colada"})  # type: ignore[attr-defined]


class TestHistorial:
    """Las busquedas, acotadas y con fecha real."""

    def test_registra_una_busqueda(self, biblioteca: MovieLibrary) -> None:
        entrada = biblioteca.add_to_history({"Title": "Interstellar"})

        assert isinstance(entrada, HistoryEntry)
        assert entrada.title == "Interstellar"
        assert len(biblioteca.history) == 1

    def test_la_fecha_por_defecto_es_la_del_reloj(
        self, biblioteca_con_reloj: MovieLibrary
    ) -> None:
        # No la cadena "hoy" del original: una fecha de verdad permite saber
        # cuando se consulto cada pelicula.
        entrada = biblioteca_con_reloj.add_to_history({"Title": "Interstellar"})

        assert entrada.searched_at == datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

    def test_la_fecha_es_una_datetime_con_zona(
        self, biblioteca: MovieLibrary
    ) -> None:
        # Con zona horaria: una naive no se puede comparar entre sesiones.
        entrada = biblioteca.add_to_history({"Title": "Interstellar"})

        assert entrada.searched_at.tzinfo is not None

    def test_acepta_una_fecha_explicita(
        self, biblioteca: MovieLibrary
    ) -> None:
        momento = datetime(2020, 5, 1, 8, 30, tzinfo=timezone.utc)

        entrada = biblioteca.add_to_history({"Title": "X"}, now=momento)

        assert entrada.searched_at == momento

    def test_el_historial_se_acota_al_maximo(
        self, biblioteca: MovieLibrary
    ) -> None:
        # El defecto que corrigio la FASE 3: el historial crecia sin limite
        # durante toda la sesion.
        for indice in range(10):
            biblioteca.add_to_history({"Title": f"Pelicula {indice}"})

        assert len(biblioteca.history) == 3

    def test_al_acotar_se_descarta_lo_mas_antiguo(
        self, biblioteca: MovieLibrary
    ) -> None:
        for indice in range(5):
            biblioteca.add_to_history({"Title": f"Pelicula {indice}"})

        titulos = [e.title for e in biblioteca.history]

        assert titulos == ["Pelicula 2", "Pelicula 3", "Pelicula 4"]

    def test_acepta_una_pelicula_del_catalogo_local(
        self, biblioteca: MovieLibrary
    ) -> None:
        entrada = biblioteca.add_to_history({"titulo": "The Godfather"})

        assert entrada.title == "The Godfather"

    def test_clear_history_vacia_el_historial(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_to_history({"Title": "A"})

        biblioteca.clear_history()

        assert biblioteca.history == ()

    def test_el_historial_no_se_modifica_por_la_vista(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_to_history({"Title": "A"})

        assert isinstance(biblioteca.history, tuple)


class TestEstadisticas:
    """Los contadores que muestra el menu."""

    def test_una_biblioteca_vacia_tiene_ceros(
        self, biblioteca: MovieLibrary
    ) -> None:
        metricas = biblioteca.statistics()

        assert metricas.total_favorites == 0
        assert metricas.total_history == 0
        assert metricas.favorites_with_rating is None

    def test_cuenta_favoritas_e_historial(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_favorite({"Title": "A"})
        biblioteca.add_favorite({"Title": "B"})
        biblioteca.add_to_history({"Title": "A"})

        metricas = biblioteca.statistics()

        assert metricas.total_favorites == 2
        assert metricas.total_history == 1

    def test_calcula_el_rating_medio(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_favorite({"Title": "A", "imdbRating": "8.0"})
        biblioteca.add_favorite({"Title": "B", "imdbRating": "9.0"})

        assert biblioteca.statistics().favorites_with_rating == 8.5

    def test_acepta_un_rating_numerico(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_favorite({"Title": "A", "imdbRating": 8.5})

        assert biblioteca.statistics().favorites_with_rating == 8.5

    @pytest.mark.parametrize("rating", [None, "", "N/A"])
    def test_ignora_las_favoritas_sin_rating(
        self, biblioteca: MovieLibrary, rating: Any
    ) -> None:
        # "N/A" es lo que devuelve OMDb cuando no hay puntuacion: contarlo como
        # cero falsearia la media.
        biblioteca.add_favorite({"Title": "A", "imdbRating": rating})
        biblioteca.add_favorite({"Title": "B", "imdbRating": "8.0"})

        assert biblioteca.statistics().favorites_with_rating == 8.0

    def test_descarta_un_rating_ilegible_sin_romper(
        self, biblioteca: MovieLibrary
    ) -> None:
        # Un solo registro corrupto no debe tirar abajo la coleccion entera.
        biblioteca.add_favorite({"Title": "A", "imdbRating": "muy buena"})
        biblioteca.add_favorite({"Title": "B", "imdbRating": "8.0"})

        assert biblioteca.statistics().favorites_with_rating == 8.0

    def test_sin_ningun_rating_valido_la_media_es_none(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_favorite({"Title": "A", "imdbRating": "N/A"})

        # None y no 0.0: 0 seria una media real.
        assert biblioteca.statistics().favorites_with_rating is None

    def test_as_dict_omite_el_rating_si_no_lo_hay(
        self, biblioteca: MovieLibrary
    ) -> None:
        # La pantalla no debe mostrar "rating medio: 0" cuando no hay ninguno.
        datos = biblioteca.statistics().as_dict()

        assert "rating_medio_favoritas" not in datos
        assert datos["total_favoritas"] == 0

    def test_as_dict_redondea_el_rating(
        self, biblioteca: MovieLibrary
    ) -> None:
        biblioteca.add_favorite({"Title": "A", "imdbRating": "8.333333"})

        assert biblioteca.statistics().as_dict()["rating_medio_favoritas"] == 8.33


class TestExportar:
    """La escritura a disco, y la barrera contra el path traversal."""

    def test_crea_el_archivo_con_la_extension_puesta(
        self, biblioteca: MovieLibrary, tmp_path: Path
    ) -> None:
        destino = biblioteca.export_to_json(tmp_path / "respaldo")

        assert destino.exists()
        assert destino.name == "respaldo"

    def test_el_archivo_contiene_las_secciones_del_esquema(
        self, biblioteca: MovieLibrary, tmp_path: Path
    ) -> None:
        # Los nombres de las secciones son el contrato con la version anterior
        # del formato: cambiarlos rompe las bibliotecas ya guardadas.
        biblioteca.add_favorite({"Title": "Interstellar"})
        biblioteca.add_to_history({"Title": "Interstellar"})

        destino = biblioteca.export_to_json(tmp_path / "respaldo.json")

        datos = json.loads(destino.read_text(encoding="utf-8"))
        assert set(datos) == {"version", "favoritas", "historial", "estadisticas"}
        assert datos["version"] == SCHEMA_VERSION

    def test_exporta_las_favoritas_y_el_historial(
        self, biblioteca_con_reloj: MovieLibrary, tmp_path: Path
    ) -> None:
        biblioteca_con_reloj.add_favorite({"Title": "Interstellar", "Year": "2014"})
        biblioteca_con_reloj.add_to_history({"Title": "Interstellar"})

        destino = biblioteca_con_reloj.export_to_json(tmp_path / "r.json")
        datos = json.loads(destino.read_text(encoding="utf-8"))

        assert datos["favoritas"][0]["Title"] == "Interstellar"
        assert datos["historial"][0]["titulo"] == "Interstellar"

    def test_la_fecha_del_historial_se_guarda_en_iso(
        self, biblioteca_con_reloj: MovieLibrary, tmp_path: Path
    ) -> None:
        # ISO 8601 es lo que `fromisoformat` sabe leer: es el contrato con el
        # round-trip.
        biblioteca_con_reloj.add_to_history({"Title": "A"})

        destino = biblioteca_con_reloj.export_to_json(tmp_path / "r.json")
        datos = json.loads(destino.read_text(encoding="utf-8"))

        assert datos["historial"][0]["fecha"] == "2026-01-15T12:00:00+00:00"

    def test_el_archivo_se_escribe_en_utf8_sin_escapes(
        self, biblioteca: MovieLibrary, tmp_path: Path
    ) -> None:
        # `ensure_ascii=False` deja "Amélie" legible en vez de "Amélie".
        biblioteca.add_favorite({"Title": "Amélie"})

        destino = biblioteca.export_to_json(tmp_path / "r.json")

        assert "Amélie" in destino.read_text(encoding="utf-8")

    def test_crea_los_directorios_intermedios(
        self, biblioteca: MovieLibrary, tmp_path: Path
    ) -> None:
        # Un subdirectorio es legitimo: lo elige el codigo, no la persona.
        destino = biblioteca.export_to_json(tmp_path / "sub" / "carpeta" / "r.json")

        assert destino.exists()

    def test_devuelve_la_ruta_escrita(self, biblioteca: MovieLibrary, tmp_path: Path) -> None:
        # Para que la interfaz pueda decir "Exportado a X".
        assert biblioteca.export_to_json(tmp_path / "r.json") == tmp_path / "r.json"

    @pytest.mark.parametrize(
        "ruta",
        ["../escape.json", "../../etc/pwned", "sub/../../escape.json"],
    )
    def test_rechaza_el_path_traversal(
        self, biblioteca: MovieLibrary, tmp_path: Path, ruta: str
    ) -> None:
        # El fallo de seguridad mas grave de la FASE 5: escribir "../../x"
        # creaba esos directorios y dejaba el archivo fuera del proyecto.
        with pytest.raises(EmptyQueryError):
            biblioteca.export_to_json(tmp_path / ruta)

    def test_un_archivo_ilegible_produce_storage_error(
        self, biblioteca: MovieLibrary, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Un disco lleno o un permiso denegado deben llegar a la interfaz como
        # un problema de almacenamiento, no como un fallo de Python.
        biblioteca.add_favorite({"Title": "A"})

        def falla(*args: Any, **kwargs: Any) -> None:
            raise PermissionError("permiso denegado")

        monkeypatch.setattr(Path, "open", falla)

        with pytest.raises(StorageError, match="escribir"):
            biblioteca.export_to_json(tmp_path / "r.json")

    def test_una_biblioteca_vacia_se_exporta_igual(
        self, biblioteca: MovieLibrary, tmp_path: Path
    ) -> None:
        # Exportar sin favoritas tiene que funcionar: es el caso de "quiero
        # respaldar mi historial".
        destino = biblioteca.export_to_json(tmp_path / "r.json")

        datos = json.loads(destino.read_text(encoding="utf-8"))
        assert datos["favoritas"] == []


class TestImportar:
    """La lectura, y sobre todo la validacion antes de tocar el estado."""

    def test_restaura_favoritas_e_historial(
        self, tmp_path: Path
    ) -> None:
        origen = tmp_path / "origen.json"
        origen.write_text(
            json.dumps(
                {
                    "version": SCHEMA_VERSION,
                    "favoritas": [{"Title": "Interstellar", "Year": "2014"}],
                    "historial": [
                        {"titulo": "Interstellar", "fecha": "2026-01-15T12:00:00+00:00"}
                    ],
                }
            ),
            encoding="utf-8",
        )

        biblioteca = MovieLibrary()
        favoritas, historial = biblioteca.import_from_json(origen)

        assert (favoritas, historial) == (1, 1)
        assert biblioteca.favorites[0]["Title"] == "Interstellar"
        assert biblioteca.history[0].title == "Interstellar"

    def test_reemplaza_el_contenido_anterior(
        self, biblioteca: MovieLibrary, tmp_path: Path
    ) -> None:
        # Importar restaura, no fusiona: el archivo es la fuente de verdad.
        biblioteca.add_favorite({"Title": "Vieja"})
        origen = tmp_path / "nuevo.json"
        origen.write_text(
            json.dumps({"favoritas": [{"Title": "Nueva"}], "historial": []}),
            encoding="utf-8",
        )

        biblioteca.import_from_json(origen)

        assert [movie_title(m) for m in biblioteca.favorites] == ["Nueva"]

    def test_un_round_trip_conserva_las_favoritas(
        self, tmp_path: Path
    ) -> None:
        # La prueba de valor: exportar e importar tiene que devolver lo mismo.
        original = MovieLibrary()
        original.add_favorite({"Title": "Interstellar", "imdbRating": "8.7"})
        original.add_favorite({"Title": "Amélie", "imdbRating": "8.3"})
        destino = original.export_to_json(tmp_path / "r.json")

        restaurada = MovieLibrary()
        restaurada.import_from_json(destino)

        assert restaurada.favorites == original.favorites
        assert restaurada.statistics().favorites_with_rating == 8.5

    def test_un_round_trip_conserva_el_historial(
        self, biblioteca_con_reloj: MovieLibrary, tmp_path: Path
    ) -> None:
        biblioteca_con_reloj.add_to_history({"Title": "A"})
        biblioteca_con_reloj.add_to_history({"Title": "B"})
        destino = biblioteca_con_reloj.export_to_json(tmp_path / "r.json")

        reloj = biblioteca_con_reloj._clock
        restaurada = MovieLibrary(max_history_entries=3, clock=reloj)
        restaurada.import_from_json(destino)

        assert [e.title for e in restaurada.history] == ["A", "B"]
        assert restaurada.history[0].searched_at == datetime(
            2026, 1, 15, 12, 0, tzinfo=timezone.utc
        )

    def test_un_archivo_inexistente_produce_storage_error(
        self, tmp_path: Path
    ) -> None:
        # "No existe" y "esta danado" son problemas distintos: la interfaz los
        # trata distinto, de ahi dos excepciones.
        biblioteca = MovieLibrary()

        with pytest.raises(StorageError, match="no existe"):
            biblioteca.import_from_json(tmp_path / "no-existe.json")

    def test_un_json_invalido_produce_corrupted_storage_error(
        self, tmp_path: Path
    ) -> None:
        origen = tmp_path / "roto.json"
        origen.write_text("{ esto no es json", encoding="utf-8")

        biblioteca = MovieLibrary()

        with pytest.raises(CorruptedStorageError, match="JSON"):
            biblioteca.import_from_json(origen)

    def test_una_lista_en_la_raiz_produce_corrupted_storage_error(
        self, tmp_path: Path
    ) -> None:
        # El archivo es valido pero no tiene la forma esperada.
        origen = tmp_path / "lista.json"
        origen.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        biblioteca = MovieLibrary()

        with pytest.raises(CorruptedStorageError, match="objeto JSON"):
            biblioteca.import_from_json(origen)

    def test_una_fecha_ilegible_produce_corrupted_storage_error(
        self, tmp_path: Path
    ) -> None:
        origen = tmp_path / "fecha.json"
        origen.write_text(
            json.dumps(
                {"favoritas": [], "historial": [{"titulo": "A", "fecha": "hoy"}]}
            ),
            encoding="utf-8",
        )

        biblioteca = MovieLibrary()

        with pytest.raises(CorruptedStorageError, match="fecha"):
            biblioteca.import_from_json(origen)

    def test_una_entrada_de_historial_con_campos_invalidos(
        self, tmp_path: Path
    ) -> None:
        origen = tmp_path / "campos.json"
        origen.write_text(
            json.dumps({"favoritas": [], "historial": [{"titulo": 123, "fecha": "2026-01-15"}]}),
            encoding="utf-8",
        )

        biblioteca = MovieLibrary()

        with pytest.raises(CorruptedStorageError):
            biblioteca.import_from_json(origen)

    def test_una_version_futura_produce_corrupted_storage_error(
        self, tmp_path: Path
    ) -> None:
        # Importar un archivo de una version posterior daria una lectura con
        # campos que este codigo no espera. Es mejor avisar que adivinar.
        origen = tmp_path / "futuro.json"
        origen.write_text(
            json.dumps({"version": SCHEMA_VERSION + 5, "favoritas": [], "historial": []}),
            encoding="utf-8",
        )

        biblioteca = MovieLibrary()

        with pytest.raises(CorruptedStorageError, match="version"):
            biblioteca.import_from_json(origen)

    def test_un_archivo_corrupto_deja_la_biblioteca_intacta(
        self, biblioteca: MovieLibrary, tmp_path: Path
    ) -> None:
        # La garantia importante: el contenido anterior se conserva hasta que la
        # lectura y la validacion terminan bien. Un fallo a medias seria peor
        # que no haber importado.
        biblioteca.add_favorite({"Title": "Interstellar"})
        origen = tmp_path / "roto.json"
        origen.write_text("{ json roto", encoding="utf-8")

        with pytest.raises(CorruptedStorageError):
            biblioteca.import_from_json(origen)

        assert [movie_title(m) for m in biblioteca.favorites] == ["Interstellar"]

    @pytest.mark.parametrize(
        "ruta", ["../escape.json", "../../etc/passwd", "sub/../../x.json"]
    )
    def test_rechaza_el_path_traversal(
        self, tmp_path: Path, ruta: str
    ) -> None:
        # Leer "../../etc/passwd" intentaria cargar un archivo del sistema como
        # si fuera una biblioteca.
        biblioteca = MovieLibrary()

        with pytest.raises(EmptyQueryError):
            biblioteca.import_from_json(tmp_path / ruta)

    def test_acepta_un_archivo_sin_la_seccion_de_version(
        self, tmp_path: Path
    ) -> None:
        # La version es opcional y por defecto es la actual: asi los archivos
        # de la version anterior, que no la tenían, siguen cargando.
        origen = tmp_path / "sin-version.json"
        origen.write_text(
            json.dumps({"favoritas": [{"Title": "A"}], "historial": []}),
            encoding="utf-8",
        )

        biblioteca = MovieLibrary()
        biblioteca.import_from_json(origen)

        assert len(biblioteca.favorites) == 1

    def test_acepta_secciones_ausentes(
        self, tmp_path: Path
    ) -> None:
        # Un archivo con solo las favoritas, o vacio del todo, es valido.
        origen = tmp_path / "minimo.json"
        origen.write_text("{}", encoding="utf-8")

        biblioteca = MovieLibrary()
        favoritas, historial = biblioteca.import_from_json(origen)

        assert (favoritas, historial) == (0, 0)


class TestHistoryEntry:
    """La entrada del historial por separado."""

    def test_as_dict_usa_los_nombres_del_esquema(
        self,
    ) -> None:
        # "titulo" y "fecha": son los nombres que espera el importador, asi que
        # tienen que coincidir en ambos sentidos.
        momento = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

        datos = HistoryEntry(title="A", searched_at=momento).as_dict()

        assert datos == {"titulo": "A", "fecha": "2026-01-15T12:00:00+00:00"}

    def test_from_dict_reconstruye_la_entrada(self) -> None:
        momento = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

        entrada = HistoryEntry.from_dict(
            {"titulo": "A", "fecha": "2026-01-15T12:00:00+00:00"}
        )

        assert entrada.title == "A"
        assert entrada.searched_at == momento

    def test_una_fecha_sin_zona_se_interpreta_como_utc(
        self,
    ) -> None:
        # Un archivo escrito por otra herramienta puede traer la hora sin
        # zona. Asumir UTC es mejor que rechazar el archivo entero.
        entrada = HistoryEntry.from_dict({"titulo": "A", "fecha": "2026-01-15T12:00:00"})

        assert entrada.searched_at.tzinfo is not None

    def test_rechaza_una_fecha_no_iso(self) -> None:
        with pytest.raises(CorruptedStorageError):
            HistoryEntry.from_dict({"titulo": "A", "fecha": "15/01/2026"})


class TestMovieTitle:
    """El helper que distingue entrada local de ficha de OMDb."""

    def test_usa_title_en_las_fichas_de_omdb(self) -> None:
        assert movie_title({"Title": "Interstellar"}) == "Interstellar"

    def test_usa_titulo_en_el_catalogo_local(self) -> None:
        # La clave local es "titulo". Sin esta distincion, las peliculas del
        # catalogo de respaldo no tendrian nombre en las favoritas.
        assert movie_title({"titulo": "The Godfather"}) == "The Godfather"

    def test_una_pelicula_sin_titulo_da_cadena_vacia(self) -> None:
        # No revienta: la interfaz puede mostrar una fila sin nombre.
        assert movie_title({}) == ""


class TestValidacionDelConstructor:
    def test_rechaza_un_historial_no_positivo(self) -> None:
        with pytest.raises(ValueError, match="max_history_entries"):
            MovieLibrary(max_history_entries=0)

    def test_rechaza_un_reloj_que_no_se_puede_llamar(self) -> None:
        with pytest.raises(TypeError, match="clock"):
            MovieLibrary(clock="no-soy-una-funcion")  # type: ignore[arg-type]

    def test_acepta_el_reloj_por_defecto(self) -> None:
        # `utc_now`, no `datetime.now` a secas: un historial sin zona no es
        # comparable entre sesiones.
        from library import utc_now

        assert utc_now().tzinfo is not None

    def test_admite_un_historial_de_una_entrada(self) -> None:
        biblioteca = MovieLibrary(max_history_entries=1)
        biblioteca.add_to_history({"Title": "A"})
        biblioteca.add_to_history({"Title": "B"})

        assert len(biblioteca.history) == 1
