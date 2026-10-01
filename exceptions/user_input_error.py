"""Errores originados por la interaccion con la persona usuaria.

Ninguno de los dos es un fallo del dominio: son la forma de expresar, en
lenguaje de dominio, dos decisiones que toma el usuario.
"""

from __future__ import annotations

from exceptions.base import MovieCatalogError


class EmptyQueryError(MovieCatalogError):
    """El usuario envio una busqueda vacia.

    Se lanza antes de construir la peticion, con lo que evita que un espacio en
    blanco llegue a la URL de la API.
    """


class UserCancelledError(MovieCatalogError):
    """El usuario cancelo la operacion.

    Cubre ``Ctrl+C`` y ``Ctrl+D`` (EOF). Antes, un ``Ctrl+C`` durante un
    ``input`` caia en uno de los ``except:`` desnudos del proyecto original y el
    programa continuaba como si nada; ahora cancela de forma limpia y con un
    codigo de salida propio.
    """