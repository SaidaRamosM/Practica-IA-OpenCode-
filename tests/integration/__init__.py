"""Pruebas de integracion: con servicios externos reales.

Solo se ejecutan con ``pytest -m integration``. Los que necesitan credencial
(OMDb) se omiten solos si ``OMDB_API_KEY`` no esta definida, de modo que la
suite sigue siendo verde en una maquina sin credenciales configuradas.

Lo que se comprueba aqui es deliberadamente estable: que la API responde, que el
formato es el esperado y que el modelo se construye. No se comprueban valores
concretos de un titulo, porque cambian con cada actualizacion del catalogo y
convertirian la suite en una fuente de falsos positivos.
"""
