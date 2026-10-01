"""Validacion y sanitizacion de las entradas que llegan de fuera.

Modulo independiente de la capa de dominio a proposito: lo necesitan la interfaz
(:mod:`ui.menu`), la persistencia (:mod:`library`), la configuracion y los
servicios, de modo que colocarlo en cualquiera de ellos crearia una dependencia
innecesaria.

Las validaciones levantan las excepciones propias de la FASE 4
(:class:`~exceptions.user_input_error.EmptyQueryError` y
:class:`~exceptions.configuration_error.ConfigError`), no ``ValueError`` a secas,
para que el resto del proyecto pueda capturarlas por tipo.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final

from exceptions import ConfigError, EmptyQueryError

#: Tope de longitud de un termino de busqueda. 200 caracteres cubren con
#: holgura cualquier titulo real, incluidos los larga Pipas de la historia del
#: cine, y evitan enviar cadenas absurdas a la API.
MAX_SEARCH_TERM_LENGTH: Final[int] = 200

#: Tope de longitud de un nombre de archivo. Los nombres de archivo практи no
#: se acercan ni a 64 caracteres en ningun sistema de ficheros habitual.
MAX_FILENAME_LENGTH: Final[int] = 64

#: Tope de longitud de una ruta completa, para la capa de persistencia.
MAX_PATH_LENGTH: Final[int] = 4096

#: Caracteres de control (C0 y DEL) y el byte nulo. No tienen sentido en un
#: titulo ni en un nombre de archivo, y algunos rompen la salida en consola.
#:
#: Ojo: ``string.printable[:32]`` NO son los caracteres de control, sino los
#: digitos y las primeras letras del alfabeto. El rango correcto son los
#: codigos 0x00-0x1F, mas el 0x7F.
_CONTROL_CHARS: Final[frozenset[str]] = frozenset(
    chr(codigo) for codigo in range(32)
) | {"\x7f"}

#: Caracteres con significado para el sistema de ficheros en Windows, macOS o
#: Linux. Se rechazan porque el proyecto puede ejecutarse en cualquiera de los
#: tres y no conviene depender de la plataforma para decidir que es seguro.
_FILENAME_FORBIDDEN: Final[frozenset[str]] = frozenset('/\\:*?"<>|')


def _check_control_chars(value: str, *, contexto: str) -> str:
    """Rechaza caracteres de control y el byte nulo."""
    if any(ch in _CONTROL_CHARS for ch in value):
        raise EmptyQueryError(f"{contexto} contiene caracteres de control no permitidos")
    return value


def validate_search_term(
    value: str,
    *,
    max_length: int = MAX_SEARCH_TERM_LENGTH,
    field: str = "la busqueda",
) -> str:
    """Normaliza y valida un termino de busqueda.

    Recorta los espacios de los extremos y rechaza lo que no puede convertirse
    en una consulta sensata: tipo incorrecto, vacio, caracteres de control y
    exceso de longitud.

    No aplica filtros de contenido: un titulo puede llevar cualquier letra,
    signo o simbolo legitimate.

    :raises TypeError: si *value* no es ``str``.
    :raises EmptyQueryError: si queda vacio, trae caracteres de control o
        excede *max_length*.
    """
    if not isinstance(value, str):
        raise TypeError(f"{field} debe ser una cadena, recibio {type(value).__name__}")

    limpio = value.strip()
    if not limpio:
        raise EmptyQueryError(f"{field} no puede estar vacia")

    _check_control_chars(limpio, contexto=field)

    if len(limpio) > max_length:
        raise EmptyQueryError(
            f"{field} es demasiado larga ({len(limpio)} caracteres, maximo {max_length})"
        )
    return limpio


def validate_filename(
    value: str,
    *,
    max_length: int = MAX_FILENAME_LENGTH,
    extension: str = ".json",
) -> str:
    """Normaliza y valida un nombre de archivo escrito por el usuario.

    Es la barrera contra **path traversal**: sin ella, escribir
    ``../../config/pwned`` en el menu de exportacion crea esos directorios y
    escribe fuera del directorio de trabajo.

    Rechaza separadores de ruta, ``..``, rutas absolutas, caracteres con
    significado para el sistema de ficheros, caracteres de control y el byte
    nulo. Si *extension* se indica, se comprueba que no venga ya anadida para
    no producir ``.json.json``.

    :raises TypeError: si *value* no es ``str``.
    :raises EmptyQueryError: si queda vacio o no es un nombre de archivo valido.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"el nombre del archivo debe ser una cadena, recibio {type(value).__name__}"
        )

    limpio = value.strip()
    if not limpio:
        raise EmptyQueryError("el nombre del archivo no puede estar vacio")

    _check_control_chars(limpio, contexto="el nombre del archivo")

    if len(limpio) > max_length:
        raise EmptyQueryError(
            f"el nombre del archivo es demasiado largo "
            f"({len(limpio)} caracteres, maximo {max_length})"
        )

    if any(ch in limpio for ch in _FILENAME_FORBIDDEN):
        raise EmptyQueryError(
            "el nombre del archivo no puede contener separadores de ruta "
            "ni los caracteres \\ / : * ? \" < > |"
        )

    if limpio in {".", ".."} or limpio.startswith(".."):
        raise EmptyQueryError("el nombre del archivo no puede ser '..' ni empezar por '..'")

    # El rechazo de separadores ya cubre de sobra las rutas absolutas; estas
    # lineas dejan explicita la intencion para quien lea el codigo.
    if limpio.startswith(("/", "\\")):
        raise EmptyQueryError("el nombre del archivo no puede ser una ruta absoluta")

    if extension and limpio.casefold().endswith(extension.casefold()):
        return limpio
    return limpio + extension


def validate_safe_path(value: str | Path) -> Path:
    """Valida una ruta de archivo rechazando el **traversal**, no los directorios.

    Se usa en la capa de persistencia (:mod:`library`), que es una API
    programatica: ahi tiene sentido escribir en un subdirectorio o en una
    ruta absoluta que el propio codigo elige.

    Lo que se rechaza es lo que convierte una escritura en una escalada:

    * cualquier componente ``..``, que permite salir del directorio base;
    * el byte nulo y los caracteres de control, que rompen rutas y consolas;
    * una longitud de componente razonable.

    A diferencia de :func:`validate_filename`, aqui los separadores y las
    rutas absolutas **si** se permiten, porque no constituyen un ataque por si
    solos: son una eleccion legitima de quien llama. La consola, que es donde
    llega el dato no confiable, usa :func:`validate_filename`, que si los
    prohibe.

    :raises EmptyQueryError: si la ruta contiene traversal o caracteres no validos.
    """
    texto = str(value)
    if not texto.strip():
        raise EmptyQueryError("la ruta del archivo no puede estar vacia")

    _check_control_chars(texto, contexto="la ruta del archivo")

    # Se examina en las dos convenciones: un Windows puede recibir "..\\" y un
    # POSIX no lo interpretaria como traversal, pero un contenedor de Windows si.
    for flavour in (PurePosixPath(texto), PureWindowsPath(texto)):
        if ".." in flavour.parts:
            raise EmptyQueryError("la ruta del archivo no puede contener '..'")

    if len(texto) > MAX_PATH_LENGTH:
        raise EmptyQueryError(f"la ruta del archivo es demasiado larga (maximo {MAX_PATH_LENGTH})")

    if not PurePosixPath(texto).name:
        raise EmptyQueryError("la ruta del archivo debe apuntar a un archivo")
    return Path(texto)


def validate_env_name(name: str) -> str:
    """Valida el nombre de una variable de entorno.

    Solo acepta el subconjunto que el shell exporta sin problemas: letras,
    digitos y ``_``, empezando por letra o ``_``.
    """
    if not isinstance(name, str) or not name:
        raise ConfigError("el nombre de la variable de entorno no puede estar vacio")
    if not (name[0].isalpha() or name[0] == "_"):
        raise ConfigError(f"nombre de variable de entorno invalido: {name!r}", field=name)
    if not all(ch.isalnum() or ch == "_" for ch in name):
        raise ConfigError(f"nombre de variable de entorno invalido: {name!r}", field=name)
    return name


__all__ = [
    "MAX_FILENAME_LENGTH",
    "MAX_PATH_LENGTH",
    "MAX_SEARCH_TERM_LENGTH",
    "validate_env_name",
    "validate_filename",
    "validate_safe_path",
    "validate_search_term",
]