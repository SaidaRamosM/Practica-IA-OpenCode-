"""Errores de persistencia de la biblioteca local."""

from __future__ import annotations

from exceptions.base import MovieCatalogError


class StorageError(MovieCatalogError):
    """No se pudo leer o escribir un archivo de la biblioteca local."""

    def __init__(self, message: str, *, path: object | None = None) -> None:
        super().__init__(message)
        self.path = path

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base} (archivo={self.path})" if self.path else base


class CorruptedStorageError(StorageError):
    """El archivo existe pero no es JSON valido o no cumple el esquema.

    Distinguirla de :class:`StorageError` permite a la interfaz decir "tus datos
    estan dañados" en vez de "no puedo escribir en disco", que son problemas muy
    distintos para el usuario.
    """