"""Capa de presentacion por consola.

* :mod:`ui.display` — formateo. Devuelve lineas de texto, no imprime nada, para
  que el formato se pueda probar sin capturar ``stdout``.
* :mod:`ui.menu` — interaccion. Es el unico sitio del proyecto que llama a
  ``input()``.

La dependencia va en un solo sentido: ``menu`` importa a ``display``.
"""

from ui.display import print_lines, render_header, render_movie, render_separator
from ui.menu import MENU, render_menu, run_menu

__all__ = [
    "MENU",
    "print_lines",
    "render_header",
    "render_menu",
    "render_movie",
    "render_separator",
    "run_menu",
]