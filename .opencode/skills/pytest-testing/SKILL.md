---
name: pytest-testing
description: Use when writing tests with pytest - structuring tests/, mocking HTTP without network, fixtures, parametrize, coverage, and integration tests that skip cleanly. Crear tests, pruebas unitarias, mocks, pytest, cobertura, fixtures.
license: MIT
metadata:
  phase: testing
  language: python
---

# Testing with pytest

Writing a suite that is fast, order-independent, and fails for one reason only.
The emphasis is on the mechanisms that *enforce* those properties, rather than
on the ones that depend on everyone remembering.

Worked examples come from a suite of 715 cases over 3,849 lines of production
code, at 91% coverage, where the unit tests could not open a socket.

## Check for injection points before writing anything

The highest-leverage step, and it is not about pytest. Read the constructor of
the class under test:

```python
class MovieService:
    def __init__(self, config: AppConfig, *, omdb: HttpClient | None = None) -> None: ...
class HttpClient:
    def __init__(self, base_url, *, session=None, max_response_bytes=None, **_) -> None: ...
class TTLCache:
    def __init__(self, ttl_seconds: float, *, clock: Clock = monotonic) -> None: ...

@classmethod
def from_env(cls, env: Mapping[str, str] | None = None) -> AppConfig: ...
```

If the dependency is already a parameter, the test needs no patching at all. On
the project these rules come from, all four injection points already existed and
a 715-case suite required **zero production changes**. When something genuinely
cannot be reached, make the smallest change that allows injection and document
it. Never restructure the code to suit the test.

Look for the same pattern in what is already there: an injectable `clock`, a
`cache` attribute, a `session` that a test can pass.

## Structure

```
tests/
├── __init__.py
├── conftest.py              payloads and models shared by everything
├── unit/
│   ├── __init__.py
│   ├── conftest.py          network guard, HTTP doubles, controllable clock
│   ├── test_movie_service.py
│   ├── test_series_service.py
│   ├── test_omdb.py
│   ├── test_tvmaze.py
│   ├── test_http_client.py
│   ├── test_validators.py
│   ├── test_cache.py
│   ├── test_config.py
│   ├── test_library.py
│   ├── test_models.py
│   ├── test_session.py
│   ├── test_display.py
│   └── test_main.py
└── integration/
    ├── __init__.py
    ├── test_omdb_integration.py
    └── test_tvmaze_integration.py
```

One file per production module, named after it. A test file covering three
modules will grow a `conftest` you cannot navigate.

`__init__.py` in every directory: without it, two `test_omdb.py` files in
different packages collide under pytest's default import mode, and the second one
silently never runs.

Keep shared data in `tests/conftest.py` and test-specific doubles in the
`conftest.py` closest to them. A helper in the root `conftest.py` is visible to
integration tests that do not need it.

## Enforce "unit tests never touch the network"

The rule is easy to state and easy to break. "Just this once" is how a suite ends
up taking ninety seconds and failing on a train.

Do not rely on discipline. Make the attempt impossible:

```python
# tests/unit/conftest.py
@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hace fallar cualquier test unitario que intente abrir un socket.

    Es ``autouse``, asi que no hay que recordarlo. Sustituye ``socket.socket`` por
    una version que lanza en ``connect``, que es el punto por el que salen las
    peticiones reales tanto de ``requests`` como de ``urllib3``.

    Que falle y no que se salte es deliberado: un test unitario que depende de la
    red no es lento, es incorrecto, y conviene enterarse al escribirlo y no
    tres meses despues.
    """
    def _conectar(self: Any, address: Any) -> Any:
        raise AssertionError(
            f"un test unitario intento abrir un socket hacia {address!r}. "
            "Simula la sesion de requests en vez de llamar a la red real."
        )

    monkeypatch.setattr(socket.socket, "connect", _conectar)
    monkeypatch.setattr(
        socket.socket, "connect_ex",
        lambda self, address: _conectar(self, address),
    )
```

`autouse` means nobody has to remember. `socket.connect` is the choke point for
both `requests` and `urllib3`, so this covers libraries you have not read.

Verify the guard works before trusting it. Write a test that deliberately tries
to reach the network and confirm it fails:

```python
def test_intenta_salir_a_la_red() -> None:
    c = OmdbClient(OMDB_BASE_URL, timeout=1.0, api_key="k")
    c.search_by_title("Interstellar")
# AssertionError: un test unitario intento abrir un socket hacia ('172.66.150.8', 443)
```

A guard nobody has seen fail is indistinguishable from a guard that does not
work. Then delete the probe test.

## Patch where the call actually is

The most common wasted afternoon. The idiomatic snippet from every tutorial:

```python
mocker.patch("api.omdb.requests.get", side_effect=requests.Timeout)
```

It does nothing here, because `api/omdb.py` never calls `requests.get`. The call
goes `OmdbClient` → `HttpClient` → `Session.get`. Patching a name that does not
exist is silently a no-op, and the test passes for the wrong reason.

Before writing the mock, find the call:

```bash
rg "requests\.get|session\.get|\.get\(" api/
```

Or check whether a shared base exists at all. Three outcomes, and each has a
right answer:

| The code does | Patch |
| --- | --- |
| call `requests.get` directly | `requests.get` at the module that calls it |
| wrap a `Session` | the `Session` object, injected via the constructor |
| have a project base client | the base client's method, e.g. `get_json` |

Use the last one when testing an API's own logic, because the class still
validates, caches, and translates errors for real:

```python
# The Response flag, the pagination, the show wrapper: all exercised,
# only the network replaced.
cliente = OmdbClient(OMDB_BASE_URL, timeout=1.0, api_key=KEY, session=FakeSession(...))
```

Split the two concerns across two files rather than mixing them: the API's
format logic in `test_omdb.py`, and transport failures in `test_http_client.py`.
A test that asserts both "the pagination stops at the total" and "a 500 becomes
`ApiResponseError`" is doing two jobs and tells you nothing about which broke.

Prefer `unittest.mock` from the standard library. `pytest-mock` is convenient but
not needed for `Mock`, `patch` and `monkeypatch`, and one fewer dependency is one
fewer thing to audit.

## Build typed fakes, not generic Mocks

`Mock` answers any attribute, so a code change can break production and leave
every test green.

Declare the attributes instead:

```python
class FakeResponse:
    """Respuesta HTTP simulada con la superficie que usa :class:`HttpClient`.

    No es un ``Mock`` generico a proposito: los atributos estan declarados, de
    modo que si ``HttpClient`` empieza a leer uno nuevo, este doble se queda
    corto y el test falla diciendo exactamente cual falta, en vez de devolver un
    ``Mock`` que acepta cualquier cosa y esconde el problema.
    """

    def __init__(self, *, status_code: int = 200, json_data: Any = None,
                 text: str = "", headers: dict[str, str] | None = None,
                 json_error: Exception | None = None) -> None:
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.text = text
        self._json_data = {} if json_data is None else json_data
        self._json_error = json_error

    def raise_for_status(self) -> None:
        """Reproduce ``requests.Response.raise_for_status`` sin el HTTP real."""
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Client Error: for url: ...",
                response=self,
            )

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._json_data
```

Support a `handler` as well, for the case where the answer depends on the
request:

```python
class FakeSession:
    def __init__(self, response=None, *, error=None, handler=None) -> None: ...
    def get(self, url, *, params=None, timeout=None):
        self.llamadas.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        if self._error is not None:
            raise self._error
        if self._handler is not None:
            return self._handler(url, dict(params or {}))
        return self._response
    def mount(self, prefix, adapter) -> None: ...
    def close(self) -> None: ...
```

Copy `params` into the recorded call. The client mutates the dict it is given
(it adds `apikey`), so holding the reference makes every assertion see the
modified version.

Recording the call turns the double into evidence. `assert_called_once_with` on a
`Mock` checks the interaction; `sesion.llamadas[0]["params"]` also lets you
assert the timeout and the query string, without asserting on internal state.

## Fixture design

Scope by how much is shared. A fixture that rebuilds a 200-line payload for
every test in a file is slow and hides which parts each test actually uses.

```python
# tests/conftest.py -- data, no behaviour
@pytest.fixture
def omdb_pelicula_encontrada() -> dict[str, Any]:
    return {"Title": "Interstellar", "Year": "2014", "imdbRating": "8.7"}

# tests/unit/conftest.py -- factories, so each test gets its own instance
@pytest.fixture
def http_client() -> Callable[..., tuple[HttpClient, FakeSession]]:
    def _crear(response=None, *, error=None, handler=None, api_key=FAKE_API_KEY):
        sesion = FakeSession(response, error=error, handler=handler)
        return HttpClient("https://api.invalid", timeout=1.0, api_key=api_key,
                          session=sesion), sesion
    return _crear
```

A factory fixture rather than a shared instance is the important one. Return the
class, not an instance, and let each test build its own: a shared `FakeSession`
accumulates calls from every test that ran before it, so the second test in a
file sees the first test's request log.

Make fixtures that write to disk use `tmp_path`. Nothing then writes into the
project directory, so the suite is safe to run in parallel.

### No credentials, ever

A fake key literal, declared once:

```python
FAKE_API_KEY = "clave-ficticia-de-prueba"
```

Never a real key, and never in a `.env` the tests depend on. For anything that
reads the environment, pass it in rather than patching the process:

```python
@pytest.fixture
def env_limpio(monkeypatch):
    """Elimina del entorno real las variables que lee ``AppConfig``."""
    for nombre in ("OMDB_API_KEY", "OMDB_TIMEOUT", "APP_DEBUG"):
        monkeypatch.delenv(nombre, raising=False)
    yield
```

`monkeypatch.delenv` matters: it makes the test independent of what the
developer has exported in their shell. Without it, the suite passes locally and
fails in CI, or the other way round.

## Test the behaviour, not the wiring

A test that asserts an internal was called is a test that fails on every
refactor and passes when the behaviour is broken. Prefer input to outcome:

```python
# Fragile: couples to the implementation.
omdb_mock.search_by_title.assert_called_once_with("Interstellar")

# Behaviour: what the caller can observe.
omdb_mock.search_by_title.return_value = omdb_pelicula_encontrada
pelicula = servicio.search_movie("Interstellar")
assert pelicula.title == "Interstellar"
assert pelicula.year == "2014"
```

The exception is interaction that *is* the contract, like "the cache prevented a
second request". Then assert on a metric rather than on a call:

```python
servicio.search_movie("Interstellar")
servicio.search_movie("Interstellar")
assert servicio.movie_cache_stats()["hits"] == 1
```

Test what a bug actually broke. On this project, the defects worth pinning were
not the happy paths:

```python
def test_un_no_encontrado_no_se_cachea(self, servicio, omdb_mock):
    """El defecto que corrigio la FASE 3: cachear tambien los fallos
    congelaba un "no existe" durante toda la sesion."""
    omdb_mock.search_by_title.return_value = None
    servicio.search_movie("Pelicula Rara")
    servicio.search_movie("Pelicula Rara")
    assert omdb_mock.search_by_title.call_count == 2

def test_un_error_de_red_no_se_cachea(self, servicio, omdb_mock):
    """Si el error quedara cacheado, un fallo transitorio impediria consultar
    esa pelicula durante el resto de la sesion."""
    omdb_mock.search_by_title.side_effect = ApiTimeoutError("se agoto el tiempo")
    with pytest.raises(ApiTimeoutError):
        servicio.search_movie("Interstellar")
    with pytest.raises(ApiTimeoutError):
        servicio.search_movie("Interstellar")
    assert omdb_mock.search_by_title.call_count == 2
```

A test that passes against the broken version teaches you nothing. Ask: would
this have failed before the fix?

## Test cases that need a controllable clock

Anything with a TTL cannot use `time.sleep`, and patching `time.monotonic` is
fragile. Inject a clock:

```python
@pytest.fixture
def reloj_falso() -> Iterator[Callable[[], float]]:
    """Reloj controlable para :class:`TTLCache`.

    Devuelve una funcion con ``.avanza(segundos)``, de modo que los tests de
    caducidad no dependen de ``time.sleep`` ni de parches de ``time.monotonic``.
    """
    instante = {"actual": 1000.0}

    def reloj() -> float:
        return instante["actual"]

    def avanza(segundos: float) -> None:
        instante["actual"] += segundos

    reloj.avanza = avanza
    yield reloj
```

Two ways to read the boundary, and both are worth having:

```python
def test_el_valor_sigue_disponible_antes_del_ttl(self, cache, reloj_falso):
    cache.set("k", "valor")
    reloj_falso.avanza(9.9)
    assert cache.get("k") == "valor"

def test_el_valor_caduca_al_llegar_al_ttl(self, cache, reloj_falso):
    """Frontera inclusiva: a los 10 s exactos ya no vale. ``>=`` y no ``>``."""
    cache.set("k", "valor")
    reloj_falso.avanza(10.0)
    assert cache.get("k") is None
```

The second is the one that catches an off-by-one. Same idea for other
boundaries: the exact max length accepted, and one more rejected.

## Parametrize instead of copy-paste

```python
@pytest.mark.parametrize(
    "termino",
    ["", "   ", "\t", "\n", " \t\n "],
    ids=["vacio", "espacios", "tabulador", "nueva-linea", "mezcla"],
)
def test_rechaza_lo_que_queda_vacio(self, termino: str) -> None:
    with pytest.raises(EmptyQueryError):
        validate_search_term(termino)
```

`ids` because a failure report reading `test_rechaza[   ]` costs more to read
than the three lines of `ids` cost to write.

Read limits from the constants, never from a literal:

```python
from utils.validators import MAX_FILENAME_LENGTH

def test_rechaza_un_nombre_mas_largo_del_limite(self) -> None:
    with pytest.raises(EmptyQueryError, match=str(MAX_FILENAME_LENGTH)):
        validate_filename("a" * (MAX_FILENAME_LENGTH + 1))
```

A test that hardcodes `64` becomes wrong the moment someone changes the limit,
and the change looks like a failure of your test rather than a behaviour change.
An early version of this suite had `max_length=5` against a six-character string
and failed for arithmetic, not for a reason related to what it tested.

## Assert on exception type before message

```python
def test_rechaza_un_titulo_vacio(self, servicio, omdb_mock):
    with pytest.raises(EmptyQueryError):
        servicio.search_movie("   ")
    omdb_mock.search_by_title.assert_not_called()
```

Type is the contract. Text is an implementation detail, and asserting on it makes
the test fail every time someone improves the wording.

When the message genuinely is the contract, assert on a fragment that identifies
the case rather than the whole sentence:

```python
def test_el_error_nombra_la_variable_que_falta(self, monkeypatch, capsys):
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    main_mod.main([])
    assert "OMDB_API_KEY" in capsys.readouterr().out
```

Assert a negative too, when the risk is a real leak:

```python
def test_no_registra_el_valor_de_la_clave(self, env_limpio, caplog):
    with caplog.at_level(logging.DEBUG, logger="config"):
        AppConfig.from_env({OMDB_API_KEY_ENV: FAKE_API_KEY})
    assert FAKE_API_KEY not in caplog.text
```

## Make each test runnable alone

The rule that keeps failures debuggable: a test may not depend on another test
having run. `pytest tests/unit/test_cache.py::test_foo` must work from a clean
process.

The usual violation is state in a module-level variable or a shared fixture
instance. The cure is the factory fixture, and `tmp_path` for anything on disk.

To be sure:

```bash
pytest tests/unit/test_movie_service.py::TestSearchMovie::test_devuelve_un_movie_cuando_omdb_encuentra
pytest -p no:randomly -x tests/unit/    # stop at the first failure
```

Run the file in reverse order, or in isolation, if a test only fails in the full
run. That pattern almost always means a shared fixture that is not actually
independent.

## Integration tests that skip cleanly

Mark them, register the marker, and skip on a missing credential:

```ini
# pytest.ini
[pytest]
testpaths = tests
addopts = --strict-markers
markers =
    integration: tests that communicate with external services
```

`--strict-markers` makes a typo in a marker name fail instead of quietly
selecting nothing.

```python
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("OMDB_API_KEY", "").strip(),
        reason="OMDB_API_KEY no esta definida: hace falta una clave real de omdbapi.com",
    ),
]
```

Put the credential in the `skipif` reason. Otherwise a skipped test reads as a
bug in the suite rather than a missing setup step.

**Do not put `-m "not integration"` in `addopts`.** It looks helpful, and it
makes `pytest -m integration` fight the default. With no default marker, all
three work as written:

```bash
pytest -v                          # everything
pytest -m "not integration" -v     # unit only, no network
pytest -m integration -v           # external services only
```

### Assert stability, not values

An integration test is checking that the API still speaks the contract you
depended on. Catalog data changes without warning, so asserting a rating or a
result count produces a test suite that fails for reasons nobody can act on.

```python
def test_la_ficha_trae_los_campos_que_la_pantalla_muestra(self, cliente_real):
    """Se comprueba la *presencia* de los campos, no sus valores: estos si son
    estables y son los que la tabla de ``constants`` necesita."""
    from constants import OMDB_MOVIE_FIELDS

    resultado = cliente_real.search_by_title(OMDB_STABLE_TITLE)
    assert resultado is not None
    for clave, _etiqueta in OMDB_MOVIE_FIELDS:
        assert clave in resultado, f"OMDb no devolvio el campo {clave!r}"
```

Where a value matters, compare loosely:

```python
# The title may carry the year in parentheses. That is not a failure.
assert OMDB_STABLE_TITLE.lower() in str(resultado["Title"]).lower()
```

Pick queries that will not disappear. A film from years ago beats a recent
release every time.

Include the inverse test, because it proves the error translation is still
working:

```python
def test_una_credencial_invalida_da_api_auth_error(self, config_real):
    cliente = OmdbClient(OMDB_BASE_URL, timeout=..., api_key="clave-falsa-para-el-test")
    try:
        with pytest.raises(ApiAuthError):
            cliente.search_by_title(OMDB_STABLE_TITLE)
    except ApiTimeoutError:
        pytest.skip("OMDb no respondio: no se puede verificar la credencial")
    finally:
        cliente.close()
```

The `skip` is there because a network hiccup must not read as a code defect.

## Coverage

```bash
pytest --cov=. --cov-report=term-missing
```

```ini
[coverage:run]
source = .
omit = tests/*
branch = True
[coverage:report]
show_missing = True
```

Omit the tests themselves: measuring your own test code is meaningless and
inflates the number. `branch = True` catches the `if` you wrote with only one arm
ever taken.

**Read the missing lines, do not chase the percentage.** Look for a module with
no tests at all, or a public function nobody calls from a test. That is a real
gap. A defensive `except` branch is not.

Set no `fail_under`. A hard threshold rewards test padding: once it is set,
someone adds a test that asserts `isinstance(x, dict)` to move a number instead
of finding a defect. The assignment behind this suite asked for 80% coverage and
explicitly said useful tests were the priority; the suite reached 91% while
leaving `ui/menu.py` at 15% on purpose, because it is the only module with
`input()` and its validation logic is already covered where it is used.

Report the number, do not gate on it.

## AAA, and readable structure

```python
def test_devuelve_un_movie_cuando_omdb_encuentra(
    self, servicio: MovieService, omdb_mock: Any, omdb_pelicula_encontrada: dict[str, Any]
) -> None:
    # Arrange
    omdb_mock.search_by_title.return_value = omdb_pelicula_encontrada

    # Act
    pelicula = servicio.search_movie("Interstellar")

    # Assert
    assert isinstance(pelicula, Movie)
    assert pelicula.title == "Interstellar"
```

Use it where a test has more than one step of setup, or where mixing them up
would be easy. A one-line assert needs no label; the comment would be noise.

The comment that earns its place is the one saying **why** the assertion is what
it is, referencing the bug it guards:

```python
def test_rechaza_un_id_invalido_sin_consultar(self, cliente_real, show_id):
    """Sin esta comprobacion, buscar el detalle de ``None`` construiria
    "/shows/None" y devolveria un 404 de TVMaze."""
    with pytest.raises(EmptyQueryError):
        cliente_real.show_details(show_id)
```

## Naming

```python
# Bad: the name says nothing about behaviour.
def test_movie_1(): ...
def test_cache(): ...

# Good: the name states the expected behaviour and the trigger.
def test_get_movie_raises_movie_not_found_when_api_returns_no_result(): ...
```

A test name is the first line of a failure report, read by someone who has not
opened the file. Make it a sentence that stands alone.

Name tests after behaviour, not after the method under test. If a class has
twenty methods, prefixing the name with the method only adds noise; the
surrounding class already says where you are.

## When a test fails, find out which one it is

A test that fails against unmodified code is telling you something. Read it as
information, not as an obstacle.

On the project these rules come from, writing the tests surfaced four real
behaviours, and every one of them became a documented test:

- **Pagination with an unparseable `totalResults` never stops.** With no usable
  total, the loop only ends on an empty page, so the defensive page cap is what
  prevents a hang. Two tests now pin that down.
- **`find_series` distinguishes id `0` from no id** with `is None`, not
  truthiness. Configuring the mock's return value makes the test fail if that
  changes.
- **`print_lines("hola")` prints one character per line**, because it iterates
  its argument. No caller does that, so it was documented as known behaviour
  rather than "fixed".
- **`render_movie` wraps the table in two separators**, so the line count is the
  field count plus two. Getting this wrong is easy, so it is asserted exactly.

Do not delete a failing test to get a green run. Either the test is wrong, in
which case fix it, or the code is wrong, in which case fix the code. Both
outcomes are better than removing the observation.

When a test is wrong, say so in the test:

```python
def test_una_barra_final_se_normaliza_en_vez_de_rechazarse(self, ruta: str) -> None:
    """Comportamiento real y aceptado: ``Path`` descarta la barra final. No es
    un agujero --no hay traversal implicito-- y quien llama recibe un ``Path``
    con la forma que espera."""
    assert validate_safe_path(ruta) == Path(ruta.rstrip("/"))
```

## Order of work

1. **Install** `pytest` into a separate dev file. `requirements.txt` is runtime
   dependencies; a deployment should not install a test framework.
2. **Write the network guard** and verify it fails a deliberate attempt.
3. **Fixtures** for the data you will reuse. Start with the payloads of the two
   APIs you integrate with.
4. **One file per module**, happy path first, to get the shape right.
5. **Error cases**, and check each one would have failed before its fix.
6. **Boundaries**: exact max accepted, one more rejected, `falsy` values that must
   not be mistaken for absence.
7. **Integration tests**, marked and skipped on a missing credential.
8. **Coverage**, then read the missing lines and decide which are real gaps.
9. **Run the suite in isolation** for anything suspicious.

## Checklist

- `requirements-dev.txt` for `pytest`; runtime file untouched
- `tests/` mirrors the production layout, `__init__.py` everywhere
- Unit tests cannot open a socket, and the guard has been seen to fail
- Mocks replace the session that actually exists, verified by reading the code
- Doubles declare their attributes, not `Mock` for everything
- Fixture factories, not shared instances
- No real credentials; environment variables deleted with `monkeypatch.delenv`
- Disk fixtures use `tmp_path`
- Every test runnable alone
- Happy path, invalid input, not found, malformed response, timeout, connection
  error, external error, expected exception
- Boundaries tested on both sides
- Integration tests marked, registered, and skipping with a clear reason
- Integration assertions about presence and shape, not exact values
- Coverage reported, not enforced
- No test deleted to get a green run
