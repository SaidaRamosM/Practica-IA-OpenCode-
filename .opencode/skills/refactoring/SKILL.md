---
name: refactoring
description: Use when refactoring messy Python - removing global mutable state, splitting god-modules, replacing bare except, adding type hints, and making state explicit. Refactorizar Python, eliminar variables globales, separar responsabilidades, quitar except desnudo.
license: MIT
metadata:
  phase: refactoring
  language: python
---

# Refactoring Python

Restructuring code that works but fights you. Every rule here comes from a
defect found in a real Python project during a six-phase refactor, and each one
names the before and the after so you can recognise it in your own code.

Work in phases. Do not mix a module split with an exception hierarchy in one
commit: when something breaks you will not know which change did it.

## Rule 1: Global mutable state becomes instance state

The defect: module-level dicts and lists that any function can read and write.
Two caches in the original project grew without limit, favourites were appended
from three different modules, and tests could not run in any order because they
shared the same dicts.

```python
# Before: anyone can mutate this, and there is no invalidation
CACHE_PELICULAS = {}
PELICULAS_FAVORITAS = []

def agregar_favorita(pelicula):
    PELICULAS_FAVORITAS.append(pelicula)
```

```python
# After: the state belongs to an object that owns its lifetime
class MovieLibrary:
    def __init__(self, *, max_history_entries: int = 100, clock: Clock = utc_now) -> None:
        self._favorites: list[Mapping[str, Any]] = []
        self._clock = clock

    def add_favorite(self, movie: Mapping[str, Any]) -> bool:
        ...
```

Two payoffs beyond testability: an injected `clock` makes time-dependent
behaviour deterministic without patching `datetime.now`, and returning `bool`
from `add_favorite` lets the caller say "already there" instead of silently
duplicating.

Give the cache a clock rather than reading the wall clock inside it:

```python
# Before
if time.time() - entry.timestamp > self.ttl:
    del self._entries[key]

# After: the test advances time instead of sleeping
def __init__(self, ttl_seconds: float, *, clock: Clock = monotonic) -> None:
    self._clock = clock

# in a test
cache = TTLCache(10.0, max_entries=2, clock=reloj_falso)
cache.set("k", "v")
reloj_falso.avanza(11)
assert cache.get("k") is None
```

## Rule 2: Return copies, not the live list

The defect: a function returned its internal list, so the caller mutated the
collection without going through any validation.

```python
# Before
@property
def favorites(self):
    return self._favorites          # the live list

# After: a copy, and the only way to change it is a method
@property
def favorites(self) -> tuple[Mapping[str, Any], ...]:
    return tuple(self._favorites)
```

Returning a `tuple` rather than a `list` is the point: `append` simply does not
exist on it, so the mistake fails loudly.

## Rule 3: Split the god-module along responsibility

The defect: one 700-line module mixed HTTP calls, business rules, formatting,
and user input. It could not be tested in pieces, and a change to menu
formatting risked breaking a network call.

Split by **who owns the change**, not by size. The test is: could this file have
a bug fixed without touching that one?

| Layer | Owns | Never does |
| --- | --- | --- |
| `api/` | HTTP, translating `requests` exceptions | import `ui` or `services` |
| `services/` | business rules, caching, returns models | print, read `input()` |
| `models/` | naming the data | know the network exists |
| `ui/display` | formatting, returns `list[str]` | print (that is `ui/menu`) |
| `ui/menu` | `input()`, printing, choosing an action | make business decisions |
| `session.py` | building the object graph | know how a screen looks |

A composition root that knows how the pieces connect is worth its own module:

```python
@dataclass(frozen=True, slots=True)
class Session:
    config: AppConfig
    movies: MovieService
    series: SeriesService
    library: MovieLibrary

    @classmethod
    def build(cls, config: AppConfig) -> Session:
        return cls(
            config=config,
            movies=MovieService(config),
            series=SeriesService(config),
            library=MovieLibrary(max_history_entries=config.max_history_entries),
        )
```

Keeping it out of `main.py` is what lets `main.py` be twenty lines of startup
logic that a test can call and assert on an exit code from.

Verify no cycles crept in. A depth-first walk over the import graph is enough:

```
main         -> session, ui.menu, ui.display, config, exceptions
session      -> services, library, config
services.*   -> api.*, models.*, cache, config, constants, exceptions
api.*        -> api.base, constants, exceptions
```

## Rule 4: Inert constants live apart from environment values

The defect: eighty-eight `*_config.py` modules, none of them ever imported,
each holding one literal.

Split by whether the value can change at runtime:

| | `constants.py` | `config.py` |
| --- | --- | --- |
| Holds | endpoints, schema keys, display labels, exit codes | anything an env var can change, plus its default |
| Import side effects | **none**: no disk, no env, no sockets | reads the environment, on purpose |
| Example | `OMDB_BASE_URL`, `OMDB_MOVIE_FIELDS` | `DEFAULT_TIMEOUT_SECONDS` |

An inert `constants.py` is worth enforcing: you can then import it anywhere,
including a test, knowing it cannot have a side effect.

## Rule 5: Replace `except:` with a domain hierarchy

The defect: bare `except:` clauses. They caught `KeyboardInterrupt` and
`SystemExit`, which derive from `BaseException`, so Ctrl+C did nothing and the
program kept running. They also swallowed bugs with no traceback.

Two halves to the fix.

**A base class for the domain**, so one `except` catches every expected failure
without absorbing the two you never want to catch:

```python
class MovieCatalogError(Exception):
    """Error base del dominio.

    Permite capturar cualquier fallo previsto del catalogo con una sola
    clausula ``except``, sin arrastrar ``KeyboardInterrupt`` ni ``SystemExit``.
    """
```

**Named exceptions** that carry the context you need to act:

```python
class ApiError(MovieCatalogError):
    def __init__(self, message: str, *, endpoint: str | None = None) -> None:
        super().__init__(message)
        self.endpoint = endpoint
```

Split by the *response to the failure*, not by the library that raised it. In
the project under refactor, 401/403 became `ApiAuthError` separately from
`ApiResponseError` because the user's action differs: re-check the credential,
do not retry.

Keep a dual-inheritance escape hatch when a broad `except ValueError` already
exists at the entry point:

```python
class ConfigError(MovieCatalogError, ValueError):
    """Heredar tambien de ValueError mantiene vivo el ``except ValueError``
    del punto de entrada, que ya existia antes que la jerarquia."""
```

A test is the only thing that keeps that guarantee from rotting:

```python
def test_config_error_si_es_value_error(self) -> None:
    assert issubclass(ConfigError, ValueError)

def test_empty_query_error_no_es_value_error(self) -> None:
    # Comprobacion negativa: si algun dia se hiciera heredar, el
    # ``except ValueError`` del punto de entrada se la tragaria sin querer.
    assert not issubclass(EmptyQueryError, ValueError)
```

## Rule 6: `print()` becomes `logging`, configured once

The defect: 158 `print()` calls used for both user-facing output and debugging.

Separate the two by destination, not by how they look:

- `ui/display.py` returns `list[str]`, or prints for the user. It is the only
  place allowed to write to the screen.
- `logging` records what happened. Configured exactly once, from the entry
  point, so no module calls `basicConfig`.

```python
def configure_logging(debug: bool, verbose: bool) -> None:
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
```

Pick a level by consequence, and stay consistent: `DEBUG` for technical detail,
`WARNING` for "recovered but unexpected", `ERROR` for "failed and could not
recover". A cache eviction is a `WARNING`, not an `ERROR`: a query was lost, the
cache did not malfunction, and `ERROR` would surface as an application failure.

Lazy `%s` formatting is not style, it is what keeps an argument out of the log
when the level is off:

```python
logger.debug("cache HIT %s", cache_key)              # not f"cache HIT {cache_key}"
```

## Rule 7: Build URLs from parameters, never by concatenation

The defect: `f"...?t={title}"`, so a title containing `&` injected an extra
criterion into the request.

```python
# Before: the user controls the query string
url = f"https://api.example.com/search?t={title}"

# After: requests encodes it, and the key is one dictionary away
query["apikey"] = self._api_key
response = self._session.get(url, params=query, timeout=self._timeout)
```

Validate the input before the call too, so a blank criterion never reaches the
network. Rejecting the empty case is not enough; see the `api-integration`
skill for the rest.

## Rule 8: Type hints on every public function, including `None`

Type hints are documentation that cannot go stale, and the checker is free.

```python
def search_movie(self, title: str) -> Movie | None:
    """Busca una pelicula por titulo, con cache.

    :returns: la pelicula, o ``None`` si no existe.
    """
```

`Movie | None` instead of `Movie` forces the caller to handle the miss. A type
hint that hides a real branch is a lie the compiler repeats back to you.

Use `Final` for module constants, `TypedDict` or `NamedTuple` for data shapes,
and `from __future__ import annotations` so the annotations are strings and cost
nothing at import.

## Rule 9: Models wrap the payload, they do not transform it

The defect: a `Movie` dataclass with renamed fields, which silently changed
what was printed and what was exported.

Wrap, name, and preserve:

```python
@dataclass(frozen=True, slots=True)
class Movie:
    """Pelicula, con vista tipada sobre el payload crudo de OMDb.

    No hay conversion ni normalizacion: el proposito es dar nombre a las
    claves, no cambiarlas.
    """
    raw: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Movie:
        return cls(raw=payload)

    @property
    def title(self) -> str:
        return str(self.get(OMDB_MOVIE_KEY, ""))
```

`frozen=True, slots=True` is a default here: immutable models cannot be half
updated, and `slots` cuts the memory of an object created per API result.

One helper serves every model, and it is where display configuration belongs:

```python
def resolve_field(payload, path, default=NOT_AVAILABLE):
    """Lee *path* admitiendo notacion de punto: "rating.average"."""
```

With a path-based reader, the display format is one tuple in `constants.py`.
Adding a column becomes an edit to that tuple instead of a copied `try/except`
per field.

## Rule 10: Inject dependencies as parameters

The defect: a service that constructed its own HTTP client internally, so it
could not be tested and could not be swapped.

```python
class MovieService:
    def __init__(self, config: AppConfig, *, omdb: HttpClient | None = None) -> None:
        self._omdb = omdb if omdb is not None else OmdbClient(
            OMDB_BASE_URL, timeout=config.request_timeout, api_key=config.omdb_api_key,
        )
```

Production passes nothing and gets the real client; tests pass a double. Same
for `session=`, `clock=`, and an `env` mapping on a config loader.

**Check for these injection points before writing a single test.** On a project
that already had them, a 715-case suite required zero production changes. When a
function is genuinely hard to test, make the smallest change that allows
injection, and document it. Never restructure to satisfy a test.

Make the boundary honest about ownership: a client passed in by the caller is
not closed by the receiver.

```python
def close(self) -> None:
    if isinstance(self._omdb, HttpClient):     # not "always close it"
        self._omdb.close()
```

## Immutability for configuration, explicit copies for data

Configuration is a frozen dataclass, so a change produces a new object and
anything holding the old one never sees a partial update.

```python
@dataclass(frozen=True, slots=True)
class AppConfig:
    request_timeout: float = DEFAULT_TIMEOUT_SECONDS

    def with_overrides(self, **changes: object) -> AppConfig:
        """Es el unico mecanismo de cambio: como la clase es congelada,
        un servicio que ya recibio una instancia no puede ver el cambio."""
        return replace(self, **changes)
```

For collections that are not configuration, hand out copies. Both rules come
from the same defect: a caller mutating shared state that something else owned.

## What to run after each phase

An AST walk catches the mechanical problems in seconds, which is faster and more
reliable than reading every file. This is the script used through the six phases
that produced this project:

```python
import ast, pathlib, sys
from collections import defaultdict

prod = sorted(p for p in pathlib.Path(".").glob("**/*.py") if "tests" not in p.parts)
modules = {".".join(p.with_suffix("").parts) for p in prod}
star = cat = bare = broad = global_kw = dead = 0
hinted = total = 0
edges = defaultdict(set)

for p in prod:
    src = p.read_text(encoding="utf-8")
    assert not src.startswith("\ufeff"), f"{p}: BOM"
    tree = ast.parse(src)
    here = ".".join(p.with_suffix("").parts)
    imported = {}

    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name == "*":
                    star += 1
                else:
                    imported[a.asname or a.name.split(".")[0]] = 1
            if isinstance(n, ast.ImportFrom) and n.module and n.level == 0 and n.module in modules:
                edges[here].add(n.module)
        if isinstance(n, ast.ExceptHandler):
            if n.type is None:
                bare += 1
            elif ast.unparse(n.type) in ("Exception", "BaseException"):
                broad += 1
        if isinstance(n, ast.Global):
            global_kw += 1
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            total += 1
            a = list(n.args.posonlyargs) + list(n.args.args) + list(n.args.kwonlyargs)
            if n.returns is not None and all(x.annotation for x in a if x.arg not in ("self", "cls")):
                hinted += 1

    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            used.add(n.id)
        elif isinstance(n, ast.Attribute):
            m = n
            while isinstance(m, ast.Attribute):
                m = m.value
            if isinstance(m, ast.Name):
                used.add(m.id)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            for w in n.value.replace("[", " ").replace("]"," ").replace(",", " ").split():
                used.add(w)
    dead += sum(1 for k in imported if k != "annotations" and k not in used)

color = defaultdict(int)
cycles = []
def dfs(u, stack):
    color[u] = 1
    for v in sorted(edges.get(u, ())):
        if color[v] == 1:
            cycles.append(" -> ".join(stack + [u, v]))
        elif color[v] == 0:
            dfs(v, stack + [u])
    color[u] = 2
for m in sorted(modules):
    if color[m] == 0:
        dfs(m, [])

print(f"modulos            : {len(prod)}")
print(f"import *           : {star}")
print(f"except desnudo     : {bare}")
print(f"except Exception   : {broad}")
print(f"sentencia global   : {global_kw}")
print(f"imports muertos    : {dead}")
print(f"type hints         : {hinted}/{total} ({hinted/total:.0%})")
print(f"ciclos de import   : {cycles or 'ninguno'}")
sys.exit(0 if not (star or bare or broad or global_kw or dead or cycles) and hinted == total else 1)
```

Run it after every phase and keep the output. Zero on all counts is the bar;
`import *`, bare `except`, `global`, dead imports and import cycles are not
stylistic preferences, they are defects.

Two notes on making it trustworthy. The dead-import detection walks string
constants too, because `logging.getLogger(__name__)` and `__all__` entries
reference names textually, and a naive walk reports them as unused. And
`except Exception:` deserves a second look rather than an automatic pass: a
handful of defensive handlers in an otherwise clean codebase usually means one
of them is hiding a real error. Narrow it to the specific types it handles.

## Order of work

When starting on unfamiliar code, do this order. Each step makes the next one
easier, and the early ones are mechanical.

1. **Inventory**: count globals, `import *`, bare `except`, and `print` calls.
   Get the numbers before changing anything, so the improvement is measurable.
2. **Untested behaviour first.** Write a test for the behaviour you are about to
   change. If a test needs a refactor to be possible, do the smallest one and
   note it.
3. **Inject dependencies.** Cheap, mechanical, and unblocks everything else.
4. **Exception hierarchy.** Once errors are named, the splits below are safer.
5. **State and immutability.** Globals to instances, live lists to copies.
6. **Module split.** Last, because it moves code and you want the code settled
   first.
7. **Logging and type hints.** Sweeps over a stable structure.
8. **Re-run the audit script** and compare against step 1.

## The result, for calibration

Six phases on a project that started as one 700-line module and a 158-`print`
program: 30 modules, 3,849 lines, zero globals, zero bare `except`, 100% type
hints on 198 functions, no import cycles, and a 715-case suite. No production
change was needed to make the tests runnable, because the injection points were
put in during the refactor rather than added for it afterwards.

That last point is the one to carry forward: **design for the test you will
write later, even if you are not writing it today.** A dependency that is easy to
inject costs one keyword argument now, and a structural rewrite later.
