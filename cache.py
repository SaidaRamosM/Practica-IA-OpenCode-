"""Cache en memoria con TTL y eviction LRU.

Sustituye a las dos globales mutables ``CACHE_PELICULAS`` y ``CACHE_SERIES``
de ``api_movies.py``, que crecian sin limite y no tenian invalidacion, y al
caos de los 50 modulos ``api_cache_*_config.py`` y los dos
``cache_manager*.py``.

Decisiones de diseno:

* **Sin estado global.** Todo el estado vive en la instancia, asi que dos
  catalogos en el mismo proceso no se pisan.
* **Reloj inyectable.** ``clock`` permite escribir tests deterministas sin
  ``sleep`` ni parches de ``time.monotonic``.
* **TTL con eviction LRU.** El peor de los dos defectos habituales se
  corrige solo: si se supera ``max_entries``, se descarta la entrada menos
  usada.
* **No cachea errores.** La cache se consulta y se escribe desde
  :mod:`services` solo tras validar la respuesta, de modo que un fallo de
  red no queda cacheado.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Callable, Generic, Iterator, TypeVar

# El limite por defecto de entradas es el mismo que el de la variable de entorno
# ``CACHE_MAX_ENTRIES``, asi que se toma de ``config`` en lugar de repetir el
# literal 256 aqui: existian dos fuentes de verdad que podian divergir.
# ``config`` no importa ``cache``, por lo que no hay ciclo.
from config import DEFAULT_CACHE_MAX_ENTRIES

logger = logging.getLogger(__name__)

T = TypeVar("T")

Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Instantanea de las metricas de una cache."""

    entries: int
    hits: int
    misses: int
    expirations: int
    evictions: int

    @property
    def hit_rate(self) -> float:
        """Proporcion de aciertos sobre el total de consultas."""
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "entries": self.entries,
            "hits": self.hits,
            "misses": self.misses,
            "expirations": self.expirations,
            "evictions": self.evictions,
            "hit_rate": round(self.hit_rate, 4),
        }


class TTLCache(Generic[T]):
    """Mapa ``str -> T`` con caducidad por tiempo y limite de tamano.

    Es segura para uso concurrente mediante un ``RLock``.
    """

    def __init__(
        self,
        ttl_seconds: float,
        *,
        max_entries: int = DEFAULT_CACHE_MAX_ENTRIES,
        clock: Clock = monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds debe ser > 0, recibio {ttl_seconds!r}")
        if max_entries <= 0:
            raise ValueError(f"max_entries debe ser > 0, recibio {max_entries!r}")
        if not callable(clock):
            raise TypeError("clock debe ser invocable")

        self._ttl = float(ttl_seconds)
        self._max_entries = int(max_entries)
        self._clock = clock
        # clave -> (instante_de_caducidad, valor)
        self._entries: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._expirations = 0
        self._evictions = 0
        self._lock = threading.RLock()

    def _evict_if_needed(self) -> None:
        """Descarte entradas hasta respetar ``max_entries`` (LRU)."""
        while len(self._entries) > self._max_entries:
            key, _ = self._entries.popitem(last=False)
            self._evictions += 1
            # Una expulsion significa que una consulta se pierde, no que la cache
            # este fallando: es merecedora de WARNING, no de ERROR.
            logger.warning(
                "cache llena (%d entradas); expulsada la clave menos usada %r",
                self._max_entries, key,
            )

    # -- lectura -----------------------------------------------------------
    def get(self, key: str) -> T | None:
        """Devuelve el valor associated a *key*, o ``None`` si no hay o caduco.

        Una entrada caducada se descarta como efecto secundario de la
        consulta, de modo que la cache no necesita un proceso de barrido.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None

            expires_at, value = entry
            if self._clock() >= expires_at:
                del self._entries[key]
                self._expirations += 1
                self._misses += 1
                return None

            # Refresh de la posicion LRU: acaba de ser usada, luego sube.
            self._entries.move_to_end(key)
            self._hits += 1
            return value

    # -- escritura ---------------------------------------------------------
    def set(self, key: str, value: T) -> None:
        """Almacena *value* bajo *key* y renueva su TTL a ``ttl_seconds``."""
        expires_at = self._clock() + self._ttl
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
            self._entries[key] = (expires_at, value)
            self._evict_if_needed()

    def invalidate(self, key: str) -> bool:
        """Elimina *key*. Devuelve ``True`` si existia."""
        with self._lock:
            return self._entries.pop(key, None) is not None

    def clear(self) -> None:
        """Vacia la cache. Las metricas se conservan."""
        with self._lock:
            self._entries.clear()

    def purge_expired(self) -> int:
        """Elimina todas las entradas caducadas. Devuelve cuantas quito."""
        now = self._clock()
        with self._lock:
            stale = [key for key, (exp, _) in self._entries.items() if now >= exp]
            for key in stale:
                del self._entries[key]
            self._expirations += len(stale)
            return len(stale)

    # -- introspeccion -----------------------------------------------------
    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                entries=len(self._entries),
                hits=self._hits,
                misses=self._misses,
                expirations=self._expirations,
                evictions=self._evictions,
            )

    def reset_stats(self) -> None:
        """Pone los contadores a cero sin tocar las entradas."""
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._expirations = 0
            self._evictions = 0

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key: object) -> bool:
        """``in`` comprueba presencia *sin* caducidad ni efectos en metricas."""
        if not isinstance(key, str):
            return False
        with self._lock:
            entry = self._entries.get(key)
            return entry is not None and self._clock() < entry[0]

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(tuple(self._entries))

    def __repr__(self) -> str:
        return (
            f"TTLCache(ttl_seconds={self._ttl!r}, max_entries={self._max_entries!r}, "
            f"size={len(self)})"
        )