"""Utilidades transversales del proyecto.

* :mod:`utils.validators` — validacion y sanitizacion de entradas externas.

No tiene dependencias de ninguna capa de dominio, de modo que puede ser
importado tanto desde la interfaz como desde la persistencia o la
configuracion sin crear ciclos.
"""

from utils.validators import (
    MAX_FILENAME_LENGTH,
    MAX_PATH_LENGTH,
    MAX_SEARCH_TERM_LENGTH,
    validate_env_name,
    validate_filename,
    validate_safe_path,
    validate_search_term,
)

__all__ = [
    "MAX_FILENAME_LENGTH",
    "MAX_PATH_LENGTH",
    "MAX_SEARCH_TERM_LENGTH",
    "validate_env_name",
    "validate_filename",
    "validate_safe_path",
    "validate_search_term",
]