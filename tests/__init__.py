"""Suite de pruebas del sistema de peliculas y series.

Estructura:

* ``unit/`` -- sin internet. Toda peticion HTTP esta simulada. Un fallo aqui
  significa que la logica de produccion cambio.
* ``integration/`` -- con internet. Se comunica con OMDb y TVMaze reales, y solo
  se ejecuta con ``pytest -m integration``.

La regla que separa ambos grupos es deliberada y la sostiene una guarda activa:
en ``unit/conftest.py`` hay una fixture ``autouse`` que hace fallar cualquier
test que intente abrir un socket. Un test unitario que consulte la red es un
error, no una prueba lenta.
"""
