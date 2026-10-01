"""Modelos de dominio.

Cada modelo es una vista tipada e inmutable sobre el payload crudo de su API:
no transforma los datos, les pone nombre. Asi, la presentacion y la
persistencia siguen leyendo exactamente lo que devolvio el servidor, y la
introduccion de los modelos no altera ni un byte de la salida.

* :mod:`models.movie` — :class:`~models.movie.Movie`
* :mod:`models.series` — :class:`~models.series.Series`

:class:`LocalMovie`, en cambio, **no** vive aqui: es el catalogo semilla
estatico, no un payload de API, asi que permanece en :mod:`constants`. Moverlo
provocaria el ciclo ``constants -> models -> constants``.
"""

from models.fields import resolve_field
from models.movie import Movie
from models.series import Series

__all__ = [
    "Movie",
    "Series",
    "resolve_field",
]