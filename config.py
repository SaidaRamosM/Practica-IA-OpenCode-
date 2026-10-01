"""Configuracion de la aplicacion: inmutable y resuelta desde el entorno.

Sustituye a los 88 modulos ``*_config.py`` y a las globales mutables
``CONFIG`` de ``api_movies.py`` y ``DEFAULT_CONFIG`` de
``config_manager*.py``.

Dos propiedades hacen el cambio de estado explicito:

1. :class:`AppConfig` es un ``dataclass(frozen=True)``. No se puede mutar
   ``config.debug = True``; hay que construir otra instancia via
   :meth:`with_overrides`. Por eso el menu de configuracion ya no puede
   alterar el estado de la capa de servicio desde fuera.
2. ``OMDB_API_KEY`` es obligatoria y se resuelve con :func:`require_env`. El
   proyecto **no contiene ninguna credencial**: ni como constante, ni como
   valor por defecto de arranque. Ver ``.env.example``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from typing import Final, Mapping

from exceptions import ConfigError

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Valores por defecto y limites
#
# Este es el unico sitio donde viven los valores que el entorno puede cambiar.
# ``constants.py`` guarda solo lo fijo (endpoints, claves de esquema, codigos de
# salida); cualquier numero que dependa de una variable de entorno, y su
# valor por defecto, se declaran aqui, junto a :meth:`AppConfig.from_env`, que
# es quien los consume.
# --------------------------------------------------------------------------
DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_CACHE_TTL_SECONDS: Final[int] = 3_600
DEFAULT_CACHE_MAX_ENTRIES: Final[int] = 256
DEFAULT_MAX_HISTORY_ENTRIES: Final[int] = 100

#: Rango admisible para el timeout de peticion. Valorados desde el entorno, no
#: ajustables: son un limite del cliente HTTP, no una preferencia.
MIN_TIMEOUT_SECONDS: Final[float] = 1.0
MAX_TIMEOUT_SECONDS: Final[float] = 120.0

#: El menu pide un entero, pero el limite es float. Se deriva en vez de repetir
#: el literal, para que no existan dos fuentes de verdad que puedan divergir.
MAX_TIMEOUT_INPUT: Final[int] = int(MAX_TIMEOUT_SECONDS)

#: Tope superior del TTL de cache. Antes vivia como literal en la validacion del
#: menu de configuracion, donde no era alcanzable desde ningun otro sitio.
MAX_CACHE_TTL_SECONDS: Final[int] = 604_800

OMDB_API_KEY_ENV: Final[str] = "OMDB_API_KEY"


def require_env(name: str, env: Mapping[str, str] | None = None) -> str:
    """Devuelve el valor de una variable de entorno **obligatoria**.

    No admite valor por defecto: una credencial jamas debe estar en el codigo,
    ni siquiera como *fallback* de arranque. Si la variable falta, se lanza
    :class:`~exceptions.configuration_error.ConfigError` nombrando la variable
    -- nunca su valor.

    *env* es inyectable para poder probar sin tocar ``os.environ``.

    :raises ConfigError: si la variable no existe o esta en blanco.
    """
    source = os.environ if env is None else env
    valor = source.get(name, "").strip()
    if not valor:
        raise ConfigError(
            f"falta la variable de entorno obligatoria {name}; "
            f"consulta .env.example para ver como definirla",
            field=name,
        )
    return valor


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Parametros de ejecucion. Inmutable: cada cambio genera otra instancia."""

    omdb_api_key: str
    request_timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    cache_max_entries: int = DEFAULT_CACHE_MAX_ENTRIES
    max_history_entries: int = DEFAULT_MAX_HISTORY_ENTRIES
    debug: bool = False
    verbose: bool = False

    def __post_init__(self) -> None:
        # Se lanza ConfigError, que hereda de ValueError: el mensaje y la
        # semantica son los correctos, y el ``except ValueError`` del punto de
        # entrada sigue capturandolo sin cambios.
        if not self.omdb_api_key.strip():
            raise ConfigError("omdb_api_key no puede estar vacia", field="omdb_api_key")
        if self.request_timeout <= 0:
            raise ConfigError("request_timeout debe ser > 0", field="request_timeout")
        if self.max_retries < 0:
            raise ConfigError("max_retries no puede ser negativo", field="max_retries")
        if self.cache_ttl_seconds <= 0:
            raise ConfigError("cache_ttl_seconds debe ser > 0", field="cache_ttl_seconds")
        if self.cache_max_entries <= 0:
            raise ConfigError("cache_max_entries debe ser > 0", field="cache_max_entries")
        if self.max_history_entries < 0:
            raise ConfigError(
                "max_history_entries no puede ser negativo", field="max_history_entries"
            )

    # -- construccion ------------------------------------------------------
    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AppConfig:
        """Construye la configuracion desde el entorno.

        ``OMDB_API_KEY`` es **obligatoria**: si falta, lanza
        :class:`~exceptions.configuration_error.ConfigError`. No existe ninguna
        credencial de reserva en el codigo.

        *env* es inyectable para poder probar sin tocar ``os.environ``.
        """
        source = os.environ if env is None else env

        # Puede lanzar ConfigError, que hereda de ValueError: el punto de
        # entrada lo captura y muestra el mensaje sin credenciales.
        api_key = require_env(OMDB_API_KEY_ENV, source)
        logger.info("%s definida (valor no registrado)", OMDB_API_KEY_ENV)

        return cls(
            omdb_api_key=api_key,
            request_timeout=_float_from_env(source, "OMDB_TIMEOUT", DEFAULT_TIMEOUT_SECONDS),
            max_retries=_int_from_env(source, "OMDB_MAX_RETRIES", DEFAULT_MAX_RETRIES),
            cache_ttl_seconds=_int_from_env(
                source, "CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS
            ),
            cache_max_entries=_int_from_env(
                source, "CACHE_MAX_ENTRIES", DEFAULT_CACHE_MAX_ENTRIES
            ),
            max_history_entries=_int_from_env(
                source, "MAX_HISTORY_ENTRIES", DEFAULT_MAX_HISTORY_ENTRIES
            ),
            debug=_bool_from_env(source, "APP_DEBUG", False),
            verbose=_bool_from_env(source, "APP_VERBOSE", False),
        )

    # -- derivados ---------------------------------------------------------
    def with_overrides(self, **changes: object) -> AppConfig:
        """Devuelve una copia con *changes* aplicados.

        Es el unico mecanismo de cambio de configuracion. Como la clase es
        congelada, un servicio que ya recibio una instancia de ``AppConfig``
        no puede ver el cambio: hay que reconstruirlo. Eso elimina la
        mutacion cruzada de estado que hacia ``main.py`` sobre ``CONFIG``.
        """
        return replace(self, **changes)

    def with_timeout(self, seconds: float) -> AppConfig:
        if not MIN_TIMEOUT_SECONDS <= seconds <= MAX_TIMEOUT_SECONDS:
            raise ConfigError(
                f"timeout fuera de rango [{MIN_TIMEOUT_SECONDS}, {MAX_TIMEOUT_SECONDS}]: {seconds}",
                field="request_timeout",
            )
        return replace(self, request_timeout=seconds)

    def with_flags(self, *, debug: bool | None = None, verbose: bool | None = None) -> AppConfig:
        changes: dict[str, bool] = {}
        if debug is not None:
            changes["debug"] = debug
        if verbose is not None:
            changes["verbose"] = verbose
        return replace(self, **changes)

    # -- validacion --------------------------------------------------------
    def validate(self) -> list[str]:
        """Devuelve la lista de problemas encontrados (vacia si es valida).

        Sustituye a los 88 ``validate_*_config()`` que solo comprueban
        ``isinstance(x, int)``.
        """
        errors: list[str] = []
        if not MIN_TIMEOUT_SECONDS <= self.request_timeout <= MAX_TIMEOUT_SECONDS:
            errors.append(
                f"request_timeout fuera de rango "
                f"[{MIN_TIMEOUT_SECONDS}, {MAX_TIMEOUT_SECONDS}]: {self.request_timeout}"
            )
        if self.max_retries < 0:
            errors.append("max_retries no puede ser negativo")
        if self.cache_ttl_seconds <= 0:
            errors.append("cache_ttl_seconds debe ser > 0")
        if self.cache_max_entries <= 0:
            errors.append("cache_max_entries debe ser > 0")
        if self.max_history_entries <= 0:
            errors.append("max_history_entries debe ser > 0")
        return errors

    def as_dict(self, *, redact_secrets: bool = True) -> dict[str, object]:
        """Representacion para diagnostico. Redacta la clave por defecto."""
        return {
            "omdb_api_key": "***" if redact_secrets else self.omdb_api_key,
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "cache_max_entries": self.cache_max_entries,
            "max_history_entries": self.max_history_entries,
            "debug": self.debug,
            "verbose": self.verbose,
        }

    def __repr__(self) -> str:
        """Oculta la clave para que no acabe en un traceback ni en un log."""
        return f"AppConfig(omdb_api_key='***', timeout={self.request_timeout!r}, ...)"


# --------------------------------------------------------------------------
# Helpers de lectura del entorno
#
# Ante un valor no numerico se registra un aviso y se usa el default, en vez
# de propagar un ValueError que abortaria la aplicacion al arrancar.
# --------------------------------------------------------------------------
def _float_from_env(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s='%s' no es un numero; se usa el valor por defecto %s", name, raw, default)
        return default


def _int_from_env(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s='%s' no es un entero; se usa el valor por defecto %s", name, raw, default)
        return default


def _bool_from_env(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on", "si", "y"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    logger.warning("%s='%s' no es un booleano; se usa el valor por defecto %s", name, raw, default)
    return default