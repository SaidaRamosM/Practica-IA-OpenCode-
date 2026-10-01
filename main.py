"""Punto de entrada del sistema de peliculas y series.

Este modulo solo arranca: construye la sesion, configura la salida y delega el
menu. Toda la logica esta en su sitio por responsabilidad:

* :mod:`api` — consumo de OMDb y TVMaze.
* :mod:`services` — logica de negocio de peliculas y series.
* :mod:`models` — modelos de dominio.
* :mod:`ui` — presentacion por consola.
* :mod:`session` — composition root.
* :mod:`cache`, :mod:`library`, :mod:`config`, :mod:`constants`,
  :mod:`exceptions` — infraestructura transversal.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

from config import AppConfig
from exceptions import (
    ApiError,
    CorruptedStorageError,
    UserCancelledError,
)
from session import Session
from ui.display import (
    configure_logging,
    configure_output,
    show_cancelled,
    show_communication_error,
    show_config_error,
    show_data_error,
    show_interrupted,
    show_startup_error,
)
from ui.menu import run_menu

EXIT_ERROR = 1
#: 130 es el codigo reservado por POSIX para "terminado por SIGINT".
EXIT_INTERRUPTED = 130

logger = logging.getLogger("peliculas")


def main(argv: Sequence[str] | None = None) -> int:
    """Arranca la aplicacion y devuelve el codigo de salida del proceso."""
    configure_output()

    try:
        config = AppConfig.from_env()
    except ValueError as exc:
        # ConfigError hereda de ValueError: se captura aqui sin cambiar el
        # contrato, y el detalle tecnico va al log mas abajo, si llega a haberlo.
        show_config_error(exc)
        return EXIT_ERROR

    configure_logging(config.debug, config.verbose)

    for warning in config.validate():
        logger.warning("configuracion: %s", warning)

    try:
        session = Session.build(config)
    except (ValueError, OSError) as exc:
        logger.error("no se pudo inicializar la aplicacion: %s", exc)
        show_startup_error(exc)
        return EXIT_ERROR

    try:
        return run_menu(session)
    except UserCancelledError:
        show_cancelled()
        return 0
    except CorruptedStorageError as exc:
        logger.exception("almacenamiento corrupto: %s", exc)
        show_data_error(exc)
        return EXIT_ERROR
    except ApiError as exc:
        logger.exception("fallo de la API: %s", exc)
        show_communication_error(exc)
        return EXIT_ERROR
    except KeyboardInterrupt:
        # Se captura explicitamente. Los ``except:`` desnudos del original se
        # lo tragaban y el programa continuaba sin dejar salir.
        show_interrupted()
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())