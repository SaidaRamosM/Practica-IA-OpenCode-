"""Pruebas de los validadores de la FASE 5.

``utils/validators.py`` es la barrera que recibe el dato no confiable, asi que
sus limites son comportamiento observable y no una implementacion interna: por
eso se comprueban aqui de forma explicita.

Los limites se leen de las constantes del propio modulo
(:data:`MAX_SEARCH_TERM_LENGTH`, :data:`MAX_FILENAME_LENGTH`) en lugar de
escribir 200 y 64 a mano. Si alguien los cambia en la FASE 7, los tests se
adaptan solos en vez de quedar obsoletos marcando un limite que ya no existe.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from exceptions import ConfigError, EmptyQueryError, MovieCatalogError
from utils.validators import (
    MAX_FILENAME_LENGTH,
    MAX_PATH_LENGTH,
    MAX_SEARCH_TERM_LENGTH,
    validate_env_name,
    validate_filename,
    validate_safe_path,
    validate_search_term,
)


class TestValidateSearchTerm:
    """``validate_search_term``: el criterio de busqueda que va a la API."""

    def test_devuelve_el_termino_tal_cual(self) -> None:
        assert validate_search_term("Batman") == "Batman"

    def test_recorta_los_espacios_de_los_extremos(self) -> None:
        assert validate_search_term("  Batman  ") == "Batman"

    def test_conserva_los_espacios_interiores(self) -> None:
        # "Blade Runner" es un caso valido: recortar de mas romperia el titulo.
        assert validate_search_term("Blade Runner") == "Blade Runner"

    @pytest.mark.parametrize(
        "termino",
        ["", "   ", "\t", "\n", " \t\n "],
        ids=["vacio", "espacios", "tabulador", "nueva-linea", "mezcla"],
    )
    def test_rechaza_lo_que_queda_vacio(self, termino: str) -> None:
        with pytest.raises(EmptyQueryError):
            validate_search_term(termino)

    @pytest.mark.parametrize("valor", [123, None, 4.2, ["Batman"], {"t": "x"}])
    def test_rechaza_tipos_que_no_son_cadena(self, valor: object) -> None:
        with pytest.raises(TypeError):
            validate_search_term(valor)  # type: ignore[arg-type]

    def test_acepta_el_limite_exacto_de_longitud(self) -> None:
        # Frontera inclusiva: 200 caracteres valen, 201 no. Un titulo real nunca
        # llega aqui, pero el limite tiene que estar bien puesto.
        assert validate_search_term("x" * MAX_SEARCH_TERM_LENGTH) == "x" * MAX_SEARCH_TERM_LENGTH

    def test_rechaza_un_caracter_mas_alla_del_limite(self) -> None:
        with pytest.raises(EmptyQueryError):
            validate_search_term("x" * (MAX_SEARCH_TERM_LENGTH + 1))

    def test_el_mensaje_de_exceso_de_longitud_cita_el_limite(self) -> None:
        with pytest.raises(EmptyQueryError, match=str(MAX_SEARCH_TERM_LENGTH)):
            validate_search_term("x" * (MAX_SEARCH_TERM_LENGTH + 1))

    @pytest.mark.parametrize(
        "termino",
        ["mal\x00nulo", "con\nsalto", "con\ttab", "borrador\x7f"],
        ids=["nulo", "nueva-linea", "tabulador", "DEL"],
    )
    def test_rechaza_caracteres_de_control(self, termino: str) -> None:
        with pytest.raises(EmptyQueryError, match="control"):
            validate_search_term(termino)

    @pytest.mark.parametrize(
        "termino",
        ["Amélie", "München", "千と千尋の神隠し", "¿Qué tal?", "100% Wolf"],
    )
    def test_acepta_acentos_y_simbolos_legitimos(self, termino: str) -> None:
        # No hay filtro de contenido: un titulo puede llevar lo que sea.
        assert validate_search_term(termino) == termino

    def test_el_limite_es_configurable_por_parametro(self) -> None:
        # "Batman" son 6 caracteres, de ahi el 6 en vez del 5.
        assert validate_search_term("Batman", max_length=6) == "Batman"
        with pytest.raises(EmptyQueryError, match="maximo 5"):
            validate_search_term("Batman", max_length=5)

    def test_el_nombre_del_campo_aparece_en_el_error(self) -> None:
        with pytest.raises(EmptyQueryError, match="el genero"):
            validate_search_term("  ", field="el genero")


class TestValidateFilename:
    """``validate_filename``: la barrera de la consola, la mas estricta."""

    def test_añade_la_extension_json_por_defecto(self) -> None:
        assert validate_filename("respaldo") == "respaldo.json"

    def test_no_duplica_la_extension_ya_presente(self) -> None:
        assert validate_filename("respaldo.json") == "respaldo.json"

    def test_no_duplica_la_extension_en_mayusculas(self) -> None:
        assert validate_filename("respaldo.JSON") == "respaldo.JSON"

    def test_acepta_una_extension_distinta(self) -> None:
        assert validate_filename("datos.txt", extension=".txt") == "datos.txt"

    def test_añade_la_extension_personalizada_al_nombre(self) -> None:
        assert validate_filename("datos", extension=".txt") == "datos.txt"

    @pytest.mark.parametrize(
        "nombre",
        [
            "../../etc/pwned",
            "..\\..\\win\\pwned",
            "sub/carpeta/archivo.json",
            "/ruta/absoluta.json",
            "C:\\Windows\\archivo.json",
            "..",
            ".",
            "..oculto",
        ],
        ids=[
            "traversal-posix",
            "traversal-windows",
            "subdirectorio",
            "absoluta-posix",
            "absoluta-windows",
            "puntos",
            "punto",
            "empieza-por-puntos",
        ],
    )
    def test_rechaza_cualquier_intento_de_path_traversal(
        self, nombre: str
    ) -> None:
        # Este es el test que importa: sin el, escribir "../../x" en el menu de
        # exportacion crearia directorios fuera del directorio de trabajo.
        with pytest.raises(EmptyQueryError):
            validate_filename(nombre)

    @pytest.mark.parametrize(
        "nombre",
        ["con*pipe", "con:dos", "con?pregunta", 'con"comilla', "con<mayor", "con>menor", "con|barra"],
    )
    def test_rechaza_caracteres_reservados_del_sistema_de_ficheros(
        self, nombre: str
    ) -> None:
        # Se rechazan en los tres sistemas operativos, no solo en el actual.
        with pytest.raises(EmptyQueryError):
            validate_filename(nombre)

    def test_acepta_el_limite_exacto_de_longitud(self) -> None:
        base = "a" * MAX_FILENAME_LENGTH
        # El limite se mide sobre el nombre sin la extension que se anade.
        assert validate_filename(base) == f"{base}.json"

    def test_rechaza_un_nombre_mas_largo_del_limite(self) -> None:
        with pytest.raises(EmptyQueryError, match=str(MAX_FILENAME_LENGTH)):
            validate_filename("a" * (MAX_FILENAME_LENGTH + 1))

    @pytest.mark.parametrize("nombre", ["", "   "])
    def test_rechaza_nombre_vacio(self, nombre: str) -> None:
        with pytest.raises(EmptyQueryError):
            validate_filename(nombre)

    @pytest.mark.parametrize(
        "nombre", ["nulo\x00.json", "salto\n.json", "DEL\x7f.json"]
    )
    def test_rechaza_caracteres_de_control(self, nombre: str) -> None:
        with pytest.raises(EmptyQueryError, match="control"):
            validate_filename(nombre)

    @pytest.mark.parametrize(
        "nombre", [123, None, ["respaldo"]]
    )
    def test_rechaza_tipos_que_no_son_cadena(self, nombre: object) -> None:
        with pytest.raises(TypeError):
            validate_filename(nombre)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "nombre", ["respaldo", "mis-peliculas", "datos_2026", "mi.archivo", "a b c"]
    )
    def test_acepta_nombres_legitimos(self, nombre: str) -> None:
        assert validate_filename(nombre) == f"{nombre}.json"

    def test_la_extension_se_compara_sin_distinguir_mayusculas(self) -> None:
        # Evita el absurdo "datos.JSON.json" que salia con un casefold erroneo.
        assert validate_filename("datos.Json", extension=".json") == "datos.Json"


class TestValidateSafePath:
    """``validate_safe_path``: la barrera de la persistencia.

    Deliberadamente mas permisiva que ``validate_filename``: acepta
    subdirectorios y rutas absolutas, porque quien la llama es codigo del
    proyecto, no una persona escribiendo a mano.
    """

    @pytest.mark.parametrize(
        "ruta",
        ["respaldo.json", "sub/respaldo.json", "a/b/c/d.json", "/tmp/absoluto.json"],
    )
    def test_acepta_rutas_legitimas(self, ruta: str) -> None:
        assert validate_safe_path(ruta) == Path(ruta)

    def test_acepta_un_objeto_path(self) -> None:
        assert validate_safe_path(Path("sub/respaldo.json")) == Path("sub/respaldo.json")

    @pytest.mark.parametrize(
        "ruta",
        [
            "../escape.json",
            "../../etc/pwned",
            "sub/../../escape.json",
            "a/../../b.json",
            "..\\..\\escape.json",
            "sub\\..\\..\\escape.json",
        ],
        ids=[
            "traversal-simple",
            "traversal-profundo",
            "traversal-tras-subdirectorio",
            "traversal-en-medio",
            "traversal-windows",
            "traversal-windows-subdirectorio",
        ],
    )
    def test_rechaza_traversal_en_cualquier_convencion(self, ruta: str) -> None:
        # Se examina la ruta como POSIX y como Windows: un contenedor de Windows
        # interpretaria "..\\" aunque el proceso corra sobre Linux.
        with pytest.raises(EmptyQueryError, match=r"\.\."):
            validate_safe_path(ruta)

    @pytest.mark.parametrize(
        "ruta", ["nulo\x00.json", "salto\n.json", "tab\t.json"]
    )
    def test_rechaza_caracteres_de_control(self, ruta: str) -> None:
        with pytest.raises(EmptyQueryError, match="control"):
            validate_safe_path(ruta)

    @pytest.mark.parametrize("ruta", ["", "   "])
    def test_rechaza_ruta_vacia(self, ruta: str) -> None:
        with pytest.raises(EmptyQueryError):
            validate_safe_path(ruta)

    def test_rechaza_ruta_demasiado_larga(self) -> None:
        with pytest.raises(EmptyQueryError, match=str(MAX_PATH_LENGTH)):
            validate_safe_path("a" * (MAX_PATH_LENGTH + 1))

    @pytest.mark.parametrize("ruta", ["/", "//", "///"])
    def test_rechaza_una_ruta_sin_nombre_de_archivo(self, ruta: str) -> None:
        # La raiz del sistema de ficheros no tiene componente final, asi que no
        # puede ser un archivo.
        with pytest.raises(EmptyQueryError, match="archivo"):
            validate_safe_path(ruta)

    @pytest.mark.parametrize("ruta", ["sub/carpeta/", "solo/"])
    def test_una_barra_final_se_normaliza_en_vez_de_rechazarse(self, ruta: str) -> None:
        # Comportamiento real y aceptado: ``Path`` descarta la barra final, asi
        # que "sub/" se convierte en "sub". No es un agujero --no hay traversal
        # implicito-- y quien llama recibe un ``Path`` con la forma que espera.
        # Lo que si pasara, si esa ruta fuera un directorio de verdad, es un
        # ``IsADirectoryError`` que ``MovieLibrary.export_to_json`` traduce a
        # ``StorageError``. Se deja constancia aqui de que es intencionado.
        assert validate_safe_path(ruta) == Path(ruta.rstrip("/"))

    def test_acepta_punto_en_el_nombre_que_no_es_traversal(self) -> None:
        # ".." se rechaza; ".." dentro de un nombre como "mi..archivo" no es
        # traversal y hay que dejarlo pasar.
        assert validate_safe_path("mi..archivo.json") == Path("mi..archivo.json")


class TestValidateEnvName:
    """``validate_env_name``: forma del nombre de una variable de entorno."""

    @pytest.mark.parametrize("nombre", ["OMDB_API_KEY", "CACHE_TTL", "_privada", "a"])
    def test_acepta_nombres_validos(self, nombre: str) -> None:
        assert validate_env_name(nombre) == nombre

    @pytest.mark.parametrize("nombre", ["", "   "])
    def test_rechaza_nombre_vacio(self, nombre: str) -> None:
        with pytest.raises(ConfigError):
            validate_env_name(nombre)

    @pytest.mark.parametrize(
        "nombre",
        ["1OMDB", "con-guion", "con espacio", "con.punto", "con$signo", "con:dos"],
    )
    def test_rechaza_caracteres_no_admitidos(self, nombre: str) -> None:
        with pytest.raises(ConfigError):
            validate_env_name(nombre)

    def test_el_error_identifica_el_campo_afectado(self) -> None:
        with pytest.raises(ConfigError) as exc_info:
            validate_env_name("con-guion")
        assert exc_info.value.field == "con-guion"

    def test_acepta_underscore_inicial(self) -> None:
        # "_PRIVADA" es una convencion habitual de shell y debe valer.
        assert validate_env_name("_PRIVADA") == "_PRIVADA"


class TestValidadoresSonExcepcionesDelDominio:
    """Los validadores lanzan excepciones propias, no ``ValueError`` a secas.

    Es lo que permite que el resto del proyecto las capture por tipo, y lo que
    impide que un ``except ValueError`` de la FASE 4 se las lleve por delante.
    """

    def test_los_rechazos_heredan_de_la_base_del_dominio(self) -> None:
        with pytest.raises(MovieCatalogError):
            validate_search_term("")
        with pytest.raises(MovieCatalogError):
            validate_filename("../x")

    def test_empty_query_error_no_es_value_error(self) -> None:
        # Comprobacion negativa: si algun dia se hiciera heredar de ValueError,
        # el ``except ValueError`` del punto de entrada se la tragaria sin
        # querer y este test avisa.
        assert not issubclass(EmptyQueryError, ValueError)

    def test_config_error_si_es_value_error(self) -> None:
        # ConfigError, en cambio, si lo es a proposito: el punto de entrada
        # captura ValueError y debe seguir funcionando.
        assert issubclass(ConfigError, ValueError)
