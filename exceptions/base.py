"""Base de la jerarquia de excepciones del dominio.

Todas las excepciones del proyecto heredan de :class:`MovieCatalogError`, de
modo que una sola clausula ``except MovieCatalogError`` captura cualquier fallo
previsto sin absorber ``KeyboardInterrupt`` ni ``SystemExit`` (derivados de
``BaseException``, no de ``Exception``).
"""

from __future__ import annotations


class MovieCatalogError(Exception):
    """Error base del dominio.

    Permite capturar cualquier fallo previsto del catalogo con una sola
    clausula ``except``, sin arrastrar ``KeyboardInterrupt`` ni ``SystemExit``,
    que antes quedaban absorbidos por los ``except:`` desnudos del proyecto
    original.
    """