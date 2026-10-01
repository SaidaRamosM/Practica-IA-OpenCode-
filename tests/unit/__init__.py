"""Pruebas unitarias: sin internet, obligatorio.

La diferencia con ``tests/integration`` no es una convencion escrita en un
documento, es una garantia mecanica. La fixture ``no_network`` de este modulo
es ``autouse``, asi que se aplica a todos los tests sin que haya que acordarse:
si alguno intenta abrir un socket, falla en el acto.
"""
