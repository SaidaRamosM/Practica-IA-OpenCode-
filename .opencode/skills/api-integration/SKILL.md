---
name: api-integration
description: Use when connecting to a REST API in Python - requests, timeouts, retries, error translation, response validation, caching, and keeping API keys out of logs. Conectar a APIs REST, requests, timeouts, reintentos, manejo de errores HTTP, credenciales.
license: MIT
metadata:
  phase: api
  language: python
---

# REST API integration

Wiring Python to an HTTP API so that network failure, malformed data, and
expired credentials are all handled as ordinary outcomes rather than surprises.

Every rule here is anchored in a real client that talks to OMDb and TVMaze. The
last one is the most important and the one no static analysis will ever catch.

## Structure: one base client, a subclass per API

A shared base holds everything that does not vary; each subclass holds only what
is specific to one service.

```
api/
├── base.py      HttpClient: session, timeout, retries, exception translation
├── omdb.py      OmdbClient: what an OMDb response means
└── tvmaze.py    TvmazeClient: what a TVMaze response means
```

The split is by *what varies*, not by convenience. If two APIs would share a
method, it belongs in `base.py`. If only one has it, it stays in the subclass.
Splitting this base per API duplicated about 120 lines that had to be fixed
twice.

The base knows about `requests`. Nothing above `api/` does. That is the whole
point: a service raising `ApiTimeoutError` instead of `requests.Timeout` means
no upper layer has to import the network library.

## Inject the session, not the client

```python
class HttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        max_retries: int = 0,
        api_key: str | None = None,
        debug: bool = False,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        session: requests.Session | None = None,
    ) -> None:
        self._owns_session = session is None
        self._session = session if session is not None else requests.Session()
        self._adapter = requests.adapters.HTTPAdapter(max_retries=max_retries)
        self._session.mount("https://", self._adapter)
        self._session.mount("http://", self._adapter)
```

Two things matter here.

**A `Session`, not `requests.get`.** A session pools the TCP connection, so a
paged search reuses one TLS handshake instead of opening a new one per request.
That is the difference between a fast feature and a slow one.

**The ownership flag.** A session passed in belongs to the caller, and closing it
would break whoever passed it:

```python
def close(self) -> None:
    """Cierra la sesion, pero solo si este cliente la creo."""
    if self._owns_session:
        self._session.close()
```

Get this right and the whole client is testable with no patching at all, which is
worth far more than it looks like.

## Timeouts are not optional

`requests.get(url)` with no timeout waits forever. On a flaky network that is a
hung program, not a slow one, and the user sees nothing at all.

```python
response = self._session.get(url, params=query, timeout=self._timeout)
```

Set the default from configuration, not from a literal:

```python
DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
MIN_TIMEOUT_SECONDS: Final[float] = 1.0
MAX_TIMEOUT_SECONDS: Final[float] = 120.0
```

The range matters. The menu asks for an integer between 1 and 120, and validating
it at the configuration boundary means the HTTP layer never sees a value that
would make requests fail instantly or hang.

**Read the timeout from the environment, but keep the number here.** A
per-request `timeout=` overrides the socket default and is a common way to lose
this guarantee one call at a time.

## Translate library exceptions into your own

This is the core of the layer. `requests` raises four exceptions that matter, and
each becomes a named one.

```python
try:
    response = self._session.get(url, params=query, timeout=self._timeout)
    response.raise_for_status()
except requests.exceptions.Timeout as exc:
    raise ApiTimeoutError(
        f"timeout de {self._timeout}s esperando a {self._base_url}", endpoint=url
    ) from exc
except requests.exceptions.ConnectionError as exc:
    raise ApiConnectionError(
        f"no se pudo conectar con {self._base_url}", endpoint=url
    ) from exc
except requests.exceptions.HTTPError as exc:
    status = getattr(exc.response, "status_code", None)
    ...
except requests.exceptions.RequestException as exc:
    raise ApiResponseError(f"fallo de red en {url}: {exc}", endpoint=url) from exc
```

Order matters, and the broad handler goes last: `Timeout`, `ConnectionError` and
`HTTPError` are all subclasses of `RequestException`.

Use `from exc` so the original stays reachable for debugging. Nobody above
`api/` should need it, but it costs nothing and it is the difference between a
diagnosable bug and a shrug.

## Distinguish "your credential is wrong" from "the service is down"

A 401 or 403 will not fix itself, and telling the user to retry is bad advice. A
500 might. Split them:

```python
AUTH_ERROR_STATUSES: Final[frozenset[int]] = frozenset({401, 403})

if status in AUTH_ERROR_STATUSES:
    raise ApiAuthError(message, endpoint=url, status=status) from exc
raise ApiResponseError(message, endpoint=url) from exc
```

Make the specific class inherit from the general one, so code that only knows
"the API failed" keeps working with no change:

```python
class ApiResponseError(ApiError): ...
class ApiAuthError(ApiResponseError):
    """401/403: la accion que debe tomar el usuario es revisar OMDB_API_KEY
    en lugar de reintentar."""
```

Then the interface can act on it: the menu prints "revisa `OMDB_API_KEY`" for an
`ApiAuthError` and the plain message otherwise. Two exceptions, two different
user actions.

## Retries: only for transport, with a bound

`HTTPAdapter(max_retries=n)` covers connection errors and some status codes. It
does **not** retry `Timeout` on a GET reliably, and you should not retry a
non-idempotent method.

Never retry an auth failure. It is not transient, and retrying a wrong key three
times is slower and no more useful than failing once.

Give pagination a defensive cap as well. If a total never matches what comes
back, an unbounded `while True` hangs the program:

```python
page += 1
if page > OMDB_MAX_SEARCH_PAGES:
    logger.warning("paginacion detenida en la pagina %d (tope defensivo)", page)
    break
```

## Validate the shape, and each API's own contract

Two layers of validation, and they catch different failures.

**Generic shape** in the base, because responses are not homogeneous:

```python
def expect_object(payload, *, endpoint: str, api: str) -> JsonObject:
    if not isinstance(payload, Mapping):
        raise ApiContractError(
            f"{api} devolvio {_json_type_name(payload)} en {endpoint}; se esperaba un objeto",
            endpoint=endpoint,
        )
    return payload

def expect_array(payload, *, endpoint: str, api: str) -> JsonArray:
    if not isinstance(payload, list):
        raise ApiContractError(...)
    return payload
```

One detail worth copying: report `MappingProxyType` as `dict` in the message. It
is an internal immutability wrapper, and "mappingproxy" in an error only
confuses whoever reads it.

Reject anything that is not a dict or a list even after `response.json()`
succeeds. `42` is valid JSON and useless as a response.

**Per-API contract** in the subclass, where the knowledge lives. OMDb signals a
miss with HTTP 200 and a marker field, which is not an error condition:

```python
OMDB_FOUND_FLAG: Final[str] = "True"

if payload.get("Response") == OMDB_FOUND_FLAG:
    return payload
logger.debug("%s no encontro la pelicula %r (%s)", API_NAME, query, payload.get("Error"))
return None
```

Return `None` for a miss and let the caller decide. In this project the service
needs to tell "not found" apart from "network failed" without catching
exceptions, and returning `None` makes that explicit. Provide a raising
sibling when a caller prefers the failure:

```python
def fetch_detail(self, title: str) -> JsonObject:
    """Como ``search_by_title``, pero lanza excepcion si no encuentra."""
    movie = self.search_by_title(title)
    if movie is None:
        raise MovieNotFoundError(title)
    return movie
```

Log the reason on a miss. The `Error` field OMDb returns is the difference
between a five-minute and a five-second diagnosis.

## Normalise the shape, keep the data

APIs return the same thing in two forms. TVMaze wraps search results in
`{"show": {...}}` but returns detail objects bare. Handle it in the model with an
idempotent function, not in the client:

```python
def extract_show(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Acepta tanto ``{"show": {...}}`` como el objeto plano. Es idempotente:
    aplicarlo a un show ya desenvuelto lo devuelve sin cambios."""
    inner = payload.get(TVMAZE_SHOW_KEY)
    return inner if isinstance(inner, Mapping) else payload
```

Idempotence is the requirement, not a nicety: it is what lets the model accept
both forms and know which one it got.

## Cap the response size

A compromised server or a bad proxy can send a body large enough to exhaust
memory. Check the header before downloading and the real size after:

```python
MAX_RESPONSE_BYTES: Final[int] = 5 * 1024 * 1024

declared = _content_length(response)
if declared is not None and declared > self._max_response_bytes:
    raise ApiContractError(f"respuesta demasiado grande desde {url}: ...", endpoint=url)
```

Treat a missing or non-numeric `Content-Length` as unknown, not as an error: not
every server sends it, and under gzip it does not reflect the decompressed size.
That is why the size is checked a second time after parsing.

## Cache successes, never failures

Cache in the **service**, not the client: the client should not know that
repeated identical queries are worth avoiding.

```python
payload = self._omdb.search_by_title(query)
if payload is None:
    logger.info("pelicula no encontrada en OMDb: %s", query)
    return None                      # do NOT cache this
movie = Movie.from_payload(payload)
self._movie_cache.set(cache_key, movie)
```

The line that matters is the early return before `set`. Caching a miss freezes
"does not exist" for the whole session, even after the title is added upstream.
The same applies to network errors: a transient failure must not be cached, or
that title is unqueryable until restart.

Two caches in the same service need separate key prefixes, or a title lookup
returns an actor's films:

```python
cache_key = f"movie:{query.casefold()}"
cache_key = f"actor:{query.casefold()}"
```

Normalise with `casefold()` rather than `lower()`; it is the correct comparison
for case-insensitive matching. Trim the whitespace, or `"Matrix"` and
`"matrix"` are two cache entries and two API calls.

## Never let the credential reach a log

**The defect this rule prevents is invisible to static analysis.** `requests`
includes the effective URL in the message of `HTTPError`, and that URL contains
`apikey=...`. Since `raise ... from exc` prints the entire chain of exceptions,
one `logger.exception()` in a 401 handler wrote the API key to the log file.
Redacting the query dict was not enough, because the leak came from the library.

Three places to redact:

```python
def _redact(self, text: str) -> str:
    """Sustituye la API key por ``***`` dentro de *text*."""
    if not text or not self._api_key:
        return text
    return text.replace(self._api_key, REDACTED)
```

1. **The response body.** A server may echo the key it received in its error
   payload, so sanitize before storing it in a message.
2. **The original exception's `args`.** Preserve type and traceback, change only
   the text:

```python
def _sanitize_exception(exc: BaseException, redact: Callable[[str], str]) -> BaseException:
    """Reescribe ``exc.args`` con el texto saneado y devuelve la excepcion.

    ``raise ... from exc`` imprime la cadena completa de excepciones, incluida
    la original de ``requests``, cuyo mensaje contiene la URL efectiva **con
    ``apikey=...`` dentro**. Sin este paso, un ``logger.exception`` basta para
    escribir la credencial en el log.
    """
    try:
        exc.args = tuple(redact(a) if isinstance(a, str) else a for a in exc.args)
    except (AttributeError, TypeError, ValueError):
        logger.debug("no se pudo sanear la excepcion original", exc_info=True)
    return exc
```

3. **The query parameters**, in the debug log:

```python
SENSITIVE_QUERY_KEYS: Final[frozenset[str]] = frozenset({
    "apikey", "api_key", "key", "token", "access_token",
    "password", "secret", "authorization",
})

def redact_query(query: Mapping[str, Any]) -> dict[str, Any]:
    """Copia de *query* con enmascarados los valores sensibles. Solo afecta a lo
    que se registra: la peticion real sigue enviando el valor original."""
    return {
        k: (REDACTED if str(k).casefold() in SENSITIVE_QUERY_KEYS else v)
        for k, v in query.items()
    }
```

Never mutate the original dict. If `redact_query` edited in place, the real
request would go out with a masked key and produce a 401 nobody can explain.

The test that catches this, and the one to keep in any client:

```python
def test_la_cadena_de_excepciones_no_filtra_la_clave(self, http_client) -> None:
    cliente, _ = http_client(FakeResponse(status_code=401, text="Invalid API key!"))
    with pytest.raises(ApiAuthError) as exc_info:
        cliente.get_json("", {"t": "x"})
    cadena = "".join(traceback.format_exception(
        type(exc_info.value), exc_info.value, exc_info.value.__traceback__))
    assert API_KEY not in cadena
    assert REDACTED in cadena
```

Asserting on `str(exc_info.value)` is not enough. Only formatting the whole
traceback chain exercises the `from exc` path that leaks.

## Get the key from the environment, with no fallback

A demo credential hardcoded as a startup fallback ends up in repositories, in
logs, and in someone else's production system.

```python
OMDB_API_KEY_ENV: Final[str] = "OMDB_API_KEY"

def require_env(name: str, env: Mapping[str, str] | None = None) -> str:
    """Devuelve el valor de una variable de entorno **obligatoria**.

    No admite valor por defecto: una credencial jamas debe estar en el codigo,
    ni siquiera como *fallback* de arranque. *env* es inyectable para poder
    probar sin tocar ``os.environ``.
    """
    source = os.environ if env is None else env
    valor = source.get(name, "").strip()
    if not valor:
        raise ConfigError(
            f"falta la variable de entorno obligatoria {name}; "
            f"consulta .env.example para ver como definirla", field=name,
        )
    return valor
```

The `env` parameter is the testability hook, and it is better than
`monkeypatch.setenv`: no global state is touched, so tests cannot leak into each
other.

Name the variable in the error, never its value. A blank or missing value is
the same failure, so treat them alike.

Ship an `.env.example` with names and empty values, never real ones, and ignore
`.env` in git.

## Checklist before shipping a client

- One `Session` reused across requests, injectable for tests
- Timeout on every call, from configuration, with a validated range
- All four `requests` exceptions translated, narrowest first
- 401/403 distinguishable from 5xx, and the user action differs
- Retries bounded, and never applied to auth failures
- Response shape validated, plus the API's own success marker
- Response size capped
- Only successes cached, keys normalised and prefixed per query type
- Credential absent from logs, exception messages, chained tracebacks, and
  `__repr__`/`as_dict`
- `close()` respects session ownership
- `https://` only
- A test that formats the full traceback chain and asserts the key is absent

That last item is the one to write first.
