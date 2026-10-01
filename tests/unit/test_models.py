"""Pruebas de los modelos: :class:`Movie`, :class:`Series` y ``resolve_field``.

Los dos modelos **envuelven** el payload en vez de sustituirlo. Eso es lo que
mantiene intacta la salida por pantalla y el JSON exportado, y es la razon por
la que se prueban tres cosas: que las propiedades leen bien, que ``get``
resuelve rutas con puntos, y que ``to_dict`` devuelve una copia del original
tal cual, sin transformaciones coladas de paso.

``extract_show`` se prueba aparte porque tiene una propiedad no obvio: es
**idempotente**, y de eso depende que ``Series`` acepte las dos formas que
devuelve TVMaze.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from constants import NOT_AVAILABLE
from models.fields import resolve_field
from models.movie import Movie
from models.series import Series, extract_show


class TestResolveField:
    """Lectura de una clave, o de una ruta de claves separadas por puntos."""

    def test_lee_una_clave_simple(self) -> None:
        assert resolve_field({"Title": "Interstellar"}, "Title") == "Interstellar"

    def test_lee_una_ruta_anidada(self) -> None:
        # Es lo que permite que `constants` describa "rating.average" sin que
        # la capa de presentacion sepa nada de la estructura de la respuesta.
        assert resolve_field({"rating": {"average": 9.3}}, "rating.average") == 9.3

    def test_lee_una_ruta_de_tres_niveles(self) -> None:
        payload = {"a": {"b": {"c": "profundo"}}}

        assert resolve_field(payload, "a.b.c") == "profundo"

    def test_devuelve_el_defecto_si_falta_la_clave(self) -> None:
        assert resolve_field({}, "Title") == NOT_AVAILABLE

    def test_devuelve_el_defecto_si_falta_un_nivel_intermedio(self) -> None:
        assert resolve_field({"rating": {}}, "rating.average") == NOT_AVAILABLE

    def test_devuelve_el_defecto_si_el_valor_es_none(self) -> None:
        # `None` se trata como ausente: mostrar "N/A" es mejor que "None".
        assert resolve_field({"Title": None}, "Title") == NOT_AVAILABLE

    def test_devuelve_el_defecto_si_se_baja_a_un_escalar(self) -> None:
        payload = {"rating": "no es un objeto"}

        assert resolve_field(payload, "rating.average") == NOT_AVAILABLE

    def test_acepta_un_defecto_propio(self) -> None:
        assert resolve_field({}, "Title", default="-") == "-"

    def test_un_valor_falsy_no_se_confunde_con_ausente(self) -> None:
        # 0 y "" son valores legitimos de una API: tratarlos como ausentes
        # haria que la pantalla mostrara N/A en lugar del dato real.
        assert resolve_field({"Year": 0}, "Year") == 0
        assert resolve_field({"Year": ""}, "Year") == ""

    def test_una_lista_es_un_valor_valido(
        self,
    ) -> None:
        # TVMaze devuelve `genres` como lista y la pantalla la imprime entera.
        generos = ["Drama", "Crime"]

        assert resolve_field({"genres": generos}, "genres") == generos


class TestMovie:
    """``Movie``: una vista con nombre sobre el payload de OMDb."""

    def test_envuelve_el_payload_sin_transformarlo(
        self, omdb_pelicula_encontrada: dict[str, Any]
    ) -> None:
        pelicula = Movie.from_payload(omdb_pelicula_encontrada)

        assert pelicula.to_dict() == omdb_pelicula_encontrada

    def test_to_dict_devuelve_una_copia(
        self, omdb_pelicula_encontrada: dict[str, Any]
    ) -> None:
        # Si devolviera el `raw` directamente, mutar el resultado alteraria el
        # modelo, que es frozen.
        pelicula = Movie.from_payload(omdb_pelicula_encontrada)

        copia = pelicula.to_dict()
        copia["Title"] = "Otro"

        assert pelicula.title == "Interstellar"

    def test_lee_el_titulo(self, movie: Movie) -> None:
        assert movie.title == "Interstellar"

    def test_lee_el_anio(self, movie: Movie) -> None:
        # Como cadena: OMDb lo devuelve asi y la pantalla lo muestra tal cual.
        assert movie.year == "2014"

    @pytest.mark.parametrize(
        "atributo",
        [
            "genre",
            "director",
            "actors",
            "plot",
            "language",
            "country",
            "awards",
            "poster",
        ],
    )
    def test_lee_los_campos_de_la_fiche(self, movie: Movie, atributo: str) -> None:
        # Todos existen y devuelven algo: una tabla vacia seria un fallo
        # silencioso en la pantalla.
        valor = getattr(movie, atributo)

        assert isinstance(valor, str)
        assert valor != ""

    def test_lee_el_rating(self, movie: Movie) -> None:
        assert movie.imdb_rating == "8.7"

    def test_un_campo_ausente_da_n_a(self) -> None:
        # El valor por defecto de la tabla de la pantalla, no una cadena vacia.
        pelicula = Movie.from_payload({"Title": "X"})

        assert pelicula.imdb_rating == NOT_AVAILABLE

    def test_el_titulo_de_una_pelicula_sin_titulo_da_cadena_vacia(
        self,
    ) -> None:
        # Distinto del resto de campos: aqui el defecto es "" y no "N/A",
        # porque la pantalla de busqueda lo trata como "sin nombre".
        assert Movie.from_payload({}).title == ""

    def test_get_resuelve_una_ruta_anidada(
        self, movie: Movie
    ) -> None:
        # El acceso que usa la capa de presentacion, y el que permite ampliar
        # la tabla de campos sin tocar el modelo.
        assert movie.get("imdbRating") == "8.7"

    def test_get_admite_una_ruta_con_puntos(
        self, omdb_pelicula_encontrada: dict[str, Any]
    ) -> None:
        payload = dict(omdb_pelicula_encontrada, ratings={"imdb": {"value": 8.7}})
        pelicula = Movie.from_payload(payload)

        assert pelicula.get("ratings.imdb.value") == 8.7

    def test_un_payload_no_json_no_revienta_al_envolverlo(self) -> None:
        # Envolver no valida: el contrato lo comprueba el cliente de la API.
        # Este test fija que la decision es deliberada.
        pelicula = Movie.from_payload({"Title": 12345})

        assert pelicula.title == "12345"

    def test_el_modelo_es_inmutable(
        self, omdb_pelicula_encontrada: dict[str, Any]
    ) -> None:
        pelicula = Movie.from_payload(omdb_pelicula_encontrada)

        with pytest.raises(Exception):
            pelicula.raw = {}  # type: ignore[misc]

    def test_from_local_usa_la_clave_del_catalogo_local(self) -> None:
        # "titulo" y no "Title": es lo que permite distinguir una entrada local
        # de una ficha de OMDb al imprimir y al exportar.
        pelicula = Movie.from_local("The Godfather", 1972, 9.2)

        assert pelicula.to_dict() == {
            "titulo": "The Godfather",
            "anio": 1972,
            "rating": 9.2,
        }

    def test_una_pelicula_local_no_tiene_imdb_rating(self) -> None:
        # No viene de OMDb, luego no hay puntuacion de IMDb que mostrar.
        pelicula = Movie.from_local("The Godfather", 1972, 9.2)

        assert pelicula.imdb_rating == NOT_AVAILABLE

    def test_el_anio_local_es_un_entero(self) -> None:
        # En el catalogo local el anio se guarda como int, a diferencia de OMDb.
        pelicula = Movie.from_local("The Godfather", 1972, 9.2)

        assert pelicula.to_dict()["anio"] == 1972


class TestExtractShow:
    """``extract_show``: desenvuelve ``{"show": {...}}`` y deja el resto igual."""

    def test_desenvuelve_el_envoltorio_show(self, tvmaze_show: Mapping[str, Any]) -> None:
        payload = {"score": 0.1, "show": dict(tvmaze_show)}

        assert extract_show(payload) == dict(tvmaze_show)

    def test_devuelve_el_payload_plano_sin_cambiarlo(
        self, tvmaze_show: Mapping[str, Any]
    ) -> None:
        # Es la forma de `/shows/{id}`. Sin esta rama, el detalle de una serie
        # no tendria nombre.
        assert extract_show(tvmaze_show) == tvmaze_show

    def test_es_idempotente(self, tvmaze_show: Mapping[str, Any]) -> None:
        # La propiedad que hace util la funcion: aplicarla a un show ya
        # desenvuelto no lo vuelve a envolver ni lo pierde.
        una_vez = extract_show({"show": dict(tvmaze_show)})

        assert extract_show(una_vez) == una_vez

    def test_ignora_un_show_que_no_es_un_mapeo(self) -> None:
        # Si `show` viniera como texto, se devolveria el payload entero en vez
        # de perderlo: la validacion es de `find_series`, no de aqui.
        payload = {"show": "texto", "score": 0.5}

        assert extract_show(payload) == payload

    def test_acepta_un_payload_vacio(self) -> None:
        assert extract_show({}) == {}


class TestSeries:
    """``Series``: la misma idea que ``Movie``, con el formato de TVMaze."""

    def test_normaliza_las_dos_formas_al_mismo_show(
        self, tvmaze_show: Mapping[str, Any]
    ) -> None:
        # La garantia central: venir de la busqueda o del detalle da el mismo
        # modelo. Si no, cada llamadaeria tendría que comprobar de que forma
        # came cada serie.
        desde_busqueda = Series.from_payload({"show": dict(tvmaze_show)})
        desde_detalle = Series.from_payload(tvmaze_show)

        assert desde_busqueda.to_dict() == desde_detalle.to_dict()

    def test_lee_el_id(self, series: Series) -> None:
        # Necesario para pedir el detalle despues.
        assert series.id == 1698

    def test_lee_el_nombre(self, series: Series) -> None:
        # TVMaze lo llama "name", no "Title" como OMDb.
        assert series.title == "Breaking Bad"

    def test_lee_los_generos(self, series: Series) -> None:
        assert series.genres == ["Drama", "Crime"]

    def test_los_generos_devuelven_una_lista(
        self, tvmaze_show: Mapping[str, Any]
    ) -> None:
        # Una copia, no la lista del payload: mutarla no debe alterar el modelo.
        serie = Series.from_payload(tvmaze_show)

        generos = serie.genres
        generos.append("Comedia")

        assert serie.genres == ["Drama", "Crime"]

    def test_los_generos_ausentes_dan_lista_vacia(self) -> None:
        # [] y no None: la pantalla itera sobre ello.
        assert Series.from_payload({"name": "X"}).genres == []

    def test_los_generos_con_tipo_raro_dan_lista_vacia(self) -> None:
        # TVMaze podria devolver otra cosa; una lista vacia es la salida segura.
        assert Series.from_payload({"name": "X", "genres": "Drama"}).genres == []

    def test_lee_el_rating_anidado(self, series: Series) -> None:
        # "rating.average": la razon de existir de la notacion con puntos.
        assert series.rating == "9.3"

    def test_lee_los_campos_de_la_fiche(
        self, series: Series
    ) -> None:
        assert series.language == "English"
        assert series.status == "Ended"
        assert series.premiered == "2008-01-20"
        assert series.ended == "2013-09-29"
        assert series.runtime == "47"

    def test_lee_el_resumen_con_html(self, series: Series) -> None:
        # TVMaze lo devuelve con etiquetas `<p>`. El modelo no las quita:
        # limpiarlas aqui cambiaria la salida y el JSON exportado.
        assert series.summary.startswith("<p>")

    def test_un_campo_ausente_da_n_a(self) -> None:
        serie = Series.from_payload({"name": "X"})

        assert serie.rating == NOT_AVAILABLE
        assert serie.language == NOT_AVAILABLE

    def test_un_id_ausente_da_none(self) -> None:
        # None y no 0: `find_series` usa `is None` para decidir si puede pedir
        # el detalle, y un 0 falsy lo haria pasar por alto.
        assert Series.from_payload({"name": "X"}).id is None

    def test_el_nombre_de_una_serie_sin_nombre_da_cadena_vacia(self) -> None:
        assert Series.from_payload({}).title == ""

    def test_to_dict_devuelve_el_show_desenvuelto(
        self, tvmaze_busqueda: list[dict[str, Any]]
    ) -> None:
        serie = Series.from_payload(tvmaze_busqueda[0])

        # Sin la clave "show": el modelo guarda el show, no el envoltorio.
        assert "show" not in serie.to_dict()
        assert serie.to_dict()["name"] == "Breaking Bad"

    def test_to_dict_devuelve_una_copia(
        self, tvmaze_show: Mapping[str, Any]
    ) -> None:
        serie = Series.from_payload(tvmaze_show)

        copia = serie.to_dict()
        copia["name"] = "Otro"

        assert serie.title == "Breaking Bad"

    def test_el_modelo_es_inmutable(self, tvmaze_show: Mapping[str, Any]) -> None:
        serie = Series.from_payload(tvmaze_show)

        with pytest.raises(Exception):
            serie.raw = {}  # type: ignore[misc]

    def test_get_resolve_una_ruta_anidada(self, series: Series) -> None:
        assert series.get("rating.average") == 9.3

    def test_construye_desde_una_consulta_real_de_tvmaze(
        self, tvmaze_busqueda: list[dict[str, Any]]
    ) -> None:
        # La forma exacta que devuelve api.tvmaze.com/search/shows, sin tocar
        # un solo campo.
        serie = Series.from_payload(tvmaze_busqueda[0])

        assert serie.title == "Breaking Bad"
        assert serie.id == 1698
        assert serie.genres == ["Drama", "Crime"]


class TestLosModelosNoHacenRedNiDisco:
    """Propiedad estructural: son modelos, no componentes activos."""

    def test_construir_un_modelo_no_abre_ninguna_conexion(self) -> None:
        # La guarda anti-red de conftest lo garantiza: si construir un
        # Movie abriera un socket, este test fallaria aqui mismo.
        Movie.from_payload({"Title": "Interstellar"})
        Series.from_payload({"name": "Breaking Bad"})

    def test_construir_un_modelo_no_crea_ningun_archivo(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cwd = tmp_path
        monkeypatch.chdir(cwd)

        Movie.from_local("X", 2020, 8.0)

        assert list(cwd.iterdir()) == []
