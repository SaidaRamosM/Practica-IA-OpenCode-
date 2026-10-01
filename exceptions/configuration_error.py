"""Error de configuracion.

:class:`ConfigError` hereda **tambien** de :class:`ValueError`, no solo de
:class:`~exceptions.base.MovieCatalogError`.

Motivo: antes de esta fase, ``config.py`` lanzaba ``ValueError`` plano, y el
punto de entrada lo captura con ``except ValueError``. Al heredar de ambos, se
puede lanzar ``ConfigError`` --que es semanticamente correcto y queda bajo la
jerarquia del dominio-- sin romper ese ``except``, ni a ningun otro llamador que
capture ese tipo.
"""

from __future__ import annotations

from exceptions.base import MovieCatalogError


class ConfigError(MovieCatalogError, ValueError):
    """La configuracion es invalida o incompleta.

    Casos que cubre: clave de API vacia, timeout fuera de rango, contadores
    negativos, TTL de cache no positivo.

    :param message: descripcion del problema.
    :param field: nombre del campo o variable de entorno afectada, si se sabe.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field