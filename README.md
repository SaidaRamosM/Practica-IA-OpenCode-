# Sistema de Películas y Series

CLI para consultar películas (OMDb) y series (TVMaze), con favoritas, historial,
exportación/importación en JSON y caché con TTL.

## Requisitos

- Python 3.10 o superior (usa `X | None`, `slots=True` y `from __future__ import annotations`)
- Las dependencias de `requirements.txt`

```bash
python -m pip install -r requirements.txt
```

## Configuración

Todo se ajusta por variables de entorno. Ningún valor sensible está en el
código.

| Variable | Por defecto | Descripción |
| --- | --- | --- |
| `OMDB_API_KEY` | *(obligatoria)* | Clave de OMDb. Sin ella la aplicación no arranca. |
| `OMDB_TIMEOUT` | `10.0` | Segundos de espera por petición. Rango admisible: 1–120. |
| `OMDB_MAX_RETRIES` | `3` | Reintentos de `requests` ante errores de transporte. |
| `CACHE_TTL_SECONDS` | `3600` | Caducidad de las entradas de caché. |
| `CACHE_MAX_ENTRIES` | `256` | Máximo de entradas por caché (evacuación LRU). |
| `MAX_HISTORY_ENTRIES` | `100` | Máximo de entradas del historial. |
| `APP_DEBUG` | `false` | Activa el log a nivel `DEBUG`. |
| `APP_VERBOSE` | `false` | Activa el log a nivel `INFO`. |

`OMDB_API_KEY` es **obligatoria**. Se consigue gratis en
<https://www.omdbapi.com/> (plan "Free"). Si falta, `AppConfig.from_env()` lanza
`ConfigError`, `main()` lo muestra y el proceso termina con código 1 sin
consultar ninguna API.

```bash
export OMDB_API_KEY=tu-clave
python main.py
```

En PowerShell: `$env:OMDB_API_KEY="tu-clave"`.

El proyecto **no contiene ninguna credencial**, ni como constante ni como valor
de arranque. `.env.example` documenta los nombres de las variables con el
valor vacío. Si copias ese archivo a `.env`, recuerda que el proyecto no lee
`.env` por sí solo (no se usa `python-dotenv`): hay que exportarlo en la
shell. `.env` está en `.gitignore`; no lo subas nunca.

Un valor mal formado en el entorno (por ejemplo `OMDB_TIMEOUT=abc`) no aborta:
se registra un aviso y se usa el valor por defecto. La excepción es la clave,
que no tiene valor por defecto posible.

La clave nunca se escribe en pantalla, en el log, en las excepciones ni en los
archivos exportados. La URL efectiva que `requests` incluye en sus mensajes de
error se sanea antes de encadenar la excepción, porque `raise ... from exc`
imprime esa cadena completa.

### `config.py` frente a `constants.py`

La regla que separa ambos módulos es **variable frente a fijo**:

| | `constants.py` | `config.py` |
| --- | --- | --- |
| Contiene | Endpoints, rutas, claves del esquema de datos, catálogos, formato de presentación, códigos de salida | Los valores que el entorno puede cambiar, y sus valores por defecto |
| Ejemplos | `OMDB_BASE_URL`, `EXIT_OPTION`, `OMDB_MOVIE_FIELDS` | `DEFAULT_TIMEOUT_SECONDS`, `MAX_TIMEOUT_SECONDS`, `DEFAULT_CACHE_MAX_ENTRIES` |
| Cambia en runtime | No | Sí, vía `AppConfig.with_*()` |

`constants.py` es inerte: importarlo no lee disco, no lee el entorno y no
abre sockets. `config.py` es el único módulo que resuelve valores del entorno,
y es quien aplica los valores por defecto de la tabla anterior.

## Uso

```bash
python main.py
```

Menú de 12 opciones: buscar por título, por actor, por serie, catálogo local de
populares y por género, favoritas, historial, estadísticas (incluye métricas de
caché), exportar, importar y configuración.

Desde la opción **Configuración** se puede cambiar el timeout, el TTL de la
caché y la clave de API. Cada cambio reconstruye los servicios con una
configuración nueva.

## Manejo de errores y logging

### Excepciones

Todas las excepciones del proyecto cuelgan de `MovieCatalogError`, lo que
permite capturarlas con una sola cláusula `except` sin absorber
`KeyboardInterrupt`:

```
MovieCatalogError
 +-- ApiError
 |    +-- ApiTimeoutError       se agotó el timeout
 |    +-- ApiConnectionError    no hubo conexión
 |    +-- ApiResponseError      estado HTTP no 2xx
 |         +-- ApiAuthError     401/403: credencial rechazada
 |         +-- ApiContractError cuerpo con forma inesperada
 +-- MovieNotFoundError
 +-- SeriesNotFoundError
 +-- ConfigError                (también hereda de ValueError)
 +-- StorageError
 |    +-- CorruptedStorageError
 +-- EmptyQueryError
 +-- UserCancelledError         Ctrl+C / Ctrl+D
```

El paquete `exceptions/` reexporta los 13+1 nombres desde `__init__.py`, de modo
que `from exceptions import ...` no cambió en ningún sitio.

`ApiAuthError` separa "la clave es incorrecta" de "el servicio falló": lo
primero no se arregla reintentando, y la interfaz lo dice así. Hereda de
`ApiResponseError`, así que el código que solo sepa que "la API falló" la sigue
capturando igual.

`ConfigError` hereda **también** de `ValueError`. `config.py` ya la lanza, pero el
punto de entrada conserva su `except ValueError`: nadie que capturara ese tipo
se rompe.

### Niveles de logging

| Nivel | Se usa para |
| --- | --- |
| `DEBUG` | Detalle técnico: URL, caché, respuestas OK |
| `INFO` | Operaciones normales: película encontrada, sesión construida |
| `WARNING` | Recuperable pero inesperado: expulsión LRU, variable mal formada |
| `ERROR` | La operación falló y no se pudo recuperar |
| `CRITICAL` | **No se usa**: no hay ninguna condición que impida continuar de forma irrecuperable. Se prefiere no añadir un nivel por obligatoriedad. |

`logging.basicConfig()` se llama **una sola vez**, en `ui.display.configure_logging`,
desde el punto de entrada. Los `print()` de la interfaz siguen en `ui/`;
ningún módulo de `api/`, `services/`, `models/` ni `cache/` imprime.

### Credenciales

`api.base.redact_query()` sustituye por `***` el valor de los parámetros
sensibles (`apikey`, `token`, `password`…) **antes** de registrarlos. La clave
sigue viajando en la petición real; solo se enmascara en la traza. `AppConfig`
también redacta en `__repr__` y `as_dict()`.

Con `APP_DEBUG=true` el log es seguro:

```
DEBUG api.base: GET https://www.omdbapi.com params={'t': 'Matrix', 'apikey': '***'} timeout=10.0
```

Enmascarar la traza no basta. El mensaje de error de `requests` incluye la URL
efectiva, que lleva `apikey=...` dentro, y `raise ... from exc` imprime esa
cadena completa de excepciones. Por eso `HttpClient._redact()` sanea también:

- el cuerpo de la respuesta, que un servidor puede reflejar con la clave dentro;
- los `args` de la excepción original de `requests`, conservando tipo y
  traceback.

Sin ese paso, un único `logger.exception()` bastaba para escribir la credencial
en el log.

### Tope de respuesta

`HttpClient` rechaza los cuerpos de más de `MAX_RESPONSE_BYTES` (5 MiB,
configurable por parámetro), comprobando `Content-Length` antes de descargar y
el tamaño leído después. Una respuesta anómala no puede agotar la memoria del
proceso.

## Validación de entradas

`utils/validators.py` concentra las comprobaciones, y hay dos porque los datos
llegan por dos caminos distintos:

| Función | Dónde se usa | Qué hace |
| --- | --- | --- |
| `validate_search_term` | `ui/menu.py` en título, actor, serie, género y clave | Máximo 200 caracteres, sin caracteres de control ni bytes nulos |
| `validate_filename` | `ui/menu.py` al exportar e importar | Solo un nombre base: sin separadores, sin `..`, máximo 64 |
| `validate_safe_path` | `library.py` al exportar e importar | Acepta subdirectorios y rutas absolutas, pero rechaza cualquier componente `..` |
| `validate_env_name` | `config.py` | Nombre de variable de entorno con forma válida |

La diferencia entre las dos funciones de archivo es deliberada. La consola es
donde llega el dato no confiable, así que exige un nombre simple. `library.py`
es una API programática: escribir en un subdirectorio o en una ruta absoluta
que el propio código elige es legítimo, y lo que constituye un ataque es
únicamente el `..`. `validate_safe_path` mantiene el orden de las dos barreras:
la interfaz valida primero y la biblioteca vuelve a validar.

## Estructura

```
.
├── main.py          Punto de entrada: solo arranca (configura y delega)
├── session.py       Composition root: Session = config + servicios + biblioteca
├── config.py        AppConfig inmutable, resuelto del entorno
├── constants.py     Constantes (URLs, esquema, formato, códigos). Sin efectos
├── pytest.ini       Configuración de pytest: marker `integration`, cobertura
├── cache.py         TTLCache: caducidad por tiempo + expulsión LRU
├── library.py       Biblioteca del usuario: favoritas, historial, persistencia
│
├── utils/           Validación de entradas no confiables
│   ├── __init__.py  reexporta los validadores
│   └── validators.py search term, filename, safe path, env name
│
├── exceptions/      Jerarquía de dominio
│   ├── __init__.py           reexporta todos los nombres
│   ├── base.py               MovieCatalogError
│   ├── api_error.py          ApiError + Timeout/Connection/Response/Auth/Contract
│   ├── movie_not_found.py    MovieNotFoundError
│   ├── series_not_found.py   SeriesNotFoundError
│   ├── configuration_error.py ConfigError (también ValueError)
│   ├── storage_error.py      StorageError, CorruptedStorageError
│   └── user_input_error.py   EmptyQueryError, UserCancelledError
│
├── api/             Consumo de APIs externas
│   ├── base.py      HttpClient compartido + redacción de credenciales
│   ├── omdb.py      Películas (OMDb)
│   └── tvmaze.py    Series (TVMaze)
│
├── models/          Modelos de dominio
│   ├── fields.py    resolve_field: lectura de rutas con puntos
│   ├── movie.py     Movie
│   └── series.py    Series + extract_show
│
├── services/        Lógica de negocio
│   ├── movie_service.py   MovieService (OMDb + catálogo local)
│   └── series_service.py  SeriesService (TVMaze)
│
├── ui/              Interfaz de consola
│   ├── display.py   Formateo y mensajes de salida
│   └── menu.py      Entrada (el único input() del proyecto) y acciones
│
├── .opencode/        Skills para agentes
│   └── skills/
│       ├── refactoring/SKILL.md      10 reglas, con el script de auditoría AST
│       ├── api-integration/SKILL.md  clientes HTTP robustos, credenciales
│       └── pytest-testing/SKILL.md    suite pytest: mocks, fixtures, cobertura
│
└── tests/           Suite de pytest
    ├── conftest.py            payloads y modelos compartidos
    ├── unit/                  sin internet (obligatorio, con guarda activa)
    │   ├── conftest.py        guarda anti-red, dobles de requests, reloj falso
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
    └── integration/           con servicios externos reales
        ├── test_omdb_integration.py
        └── test_tvmaze_integration.py
```

### Capas y dependencias

Cada capa depende solo de las que están debajo. **No hay ciclos**, y el grafo
se puede comprobar con un recorrido en profundidad sobre los imports:

```
tests.*      → todo lo anterior, y nada del revés: la producción no importa
               a `tests/`, así que la suite no altera el grafo del proyecto
main         → session, ui.menu, ui.display, config, exceptions
ui.menu      → ui.display, session, library, config, constants, exceptions
ui.display   → models.fields, models.series, constants
session      → services, library, config
services.*   → api.*, models.*, cache, config, constants, exceptions
api.*        → api.base, constants, exceptions
models.*     → models.fields, constants
config       → constants, exceptions
utils.*      → exceptions
```

Los módulos sin dependencias internas (`constants`, `exceptions.base`) son las
hojas del grafo.

### Responsabilidad de cada capa

| Capa | Puede | No puede |
| --- | --- | --- |
| `api/` | hablar HTTP, traducir excepciones de red | importar `ui` ni `services` |
| `services/` | aplicar reglas de negocio y caché, devolver modelos | imprimir ni leer `input()` |
| `models/` | nombrar los datos | conocer la red |
| `ui/display` | formatear a `list[str]` | imprimir directamente (lo hace `ui.menu`) |
| `ui/menu` | `input()`, imprimir, elegir acción | tomar decisiones de negocio |
| `session` | construir el grafo de objetos | saber cómo se ve una pantalla |

`input()` aparece **solo** en `ui/menu._prompt`. Ningún servicio, modelo ni
cliente de API imprime o lee de la entrada estándar.

## Decisiones de diseño

**Sin variables globales.** El estado vive en objetos explícitos. `Session`
(`session.py`) agrupa configuración, servicios y biblioteca, y se reconstruye
completa cuando la configuración cambia. `AppConfig` es `frozen=True`: cambiar
el timeout produce un objeto nuevo, nunca una mutación compartida.

**Errores de dominio.** `requests` no se propaga más allá de `api/`:
sus excepciones se traducen a `ApiTimeoutError`, `ApiConnectionError`,
`ApiResponseError` y `ApiContractError`, todas bajo `MovieCatalogError`. Eso
permite capturarlas con una sola cláusula `except` sin absorber `KeyboardInterrupt`.

**Caché con límites.** `TTLCache` combina caducidad por tiempo con expulsión
LRU y solo cachea respuestas validadas: un "no encontrado" o un error de red
no se cachean. Acepta un reloj inyectable, lo que permite tests deterministas.

**Testabilidad por inyección, no por parcheo.** `MovieService` y `SeriesService`
aceptan su cliente por parámetro, `HttpClient` acepta su `Session`,
`TTLCache` y `MovieLibrary` aceptan su reloj, y `AppConfig.from_env` acepta el
entorno. Los cuatro puntos que la suite necesita ya existían antes de escribir
un solo test, así que la fase 6 no reformó nada de producción. Es la diferencia
entre una suite que obliga a refactorizar y una que se apoya en el diseño.

**Sin efectos secundarios en la importación.** Importar cualquier módulo no lee
disco ni crea directorios. La configuración se resuelve en `AppConfig.from_env()`
y las conexiones HTTP se crean de forma explícita.

**Sin credenciales en el repositorio.** `OMDB_API_KEY` es obligatoria y no tiene
valor de reserva. Una credencial de demo en el código significa acabarla en los
logs de cualquiera, y quien la lea puede agotarla. La clave se pide al
entorno, se redacta en pantalla y en el log, y se sanea también en las
excepciones encadenadas. `constants.py` no la contiene, así que importarlo es
inerte y no filtra nada.

**Renderizado declarativo.** `OMDB_MOVIE_FIELDS` y `TVMAZE_SHOW_FIELDS` en
`constants.py` describen las columnas a mostrar, así que la UI se amplía
editando una tupla en lugar de copiar un bloque `try/except` por campo.

**Modelos que envuelven el payload.** `Movie` y `Series` no sustituyen al
diccionario de la API: lo guardan en `raw` y lo leen por rutas. La presentación
sigue usando las tablas de campos como única fuente del formato, de modo que la
salida por pantalla y el JSON exportado no cambian. `to_dict()` devuelve una
copia del payload original.

**Menú dirigido por tabla.** Las opciones del menú de configuración viven en
`_CONFIG_HANDLERS` (`ui/menu.py`), y el rango que el menú valida se deriva con
`max(_CONFIG_HANDLERS)`. Antes el rango (`high=5`) y los casos resueltos
(`if option == 1..5`) estaban escritos por separado, de modo que añadir una
opción la hacía aceptable pero inalcanzable.

## Pruebas

La suite usa `pytest` y vive en `tests/`. Las dependencias son de desarrollo, no
de ejecución, y por eso van en un archivo aparte:

```bash
python -m pip install -r requirements-dev.txt
```

| Comando | Qué ejecuta |
| --- | --- |
| `pytest -v` | Todo |
| `pytest -m "not integration" -v` | Solo unitarios, sin internet |
| `pytest -m integration -v` | Solo los que hablan con OMDb y TVMaze reales |
| `pytest --cov=. --cov-report=term-missing` | Con cobertura |

### La regla: unitario sin internet

`tests/unit/` no puede abrir un socket, y no por convención: `unit/conftest.py`
tiene una fixture `autouse` que sustituye `socket.connect` por una versión que
falla. Un test unitario que intente salir a la red se rompe en el acto, así que
no depende de que nadie se acuerde.

El doble de la red es `FakeSession`, no un parche de `requests.get`. La razón es
concreta: `api/omdb.py` y `api/tvmaze.py` nunca llaman a `requests.get`, todo
pasa por `HttpClient` → `Session.get`. Parchear donde no se usa no surte efecto.

Los tests de `api/omdb.py` y `api/tvmaze.py` cubren dos niveles: la lógica
propia de cada API (la marca `Response`, la paginación, el envoltorio `show`)
con `get_json` simulado, y los errores de red con `Session.get`, en
`test_http_client.py`.

### Fixtures

`tests/conftest.py` tiene los datos compartidos: payloads de OMDb y TVMaze,
modelos ya construidos y la configuración de test. `tests/unit/conftest.py` tiene
la guarda anti-red, las fábricas de clientes con sesión simulada y un reloj
controlable para los tests de TTL.

Ningún archivo de `tests/` contiene una credencial real. La clave de OMDb es un
literal ficticio, y los tests de `config` usan el parámetro `env` de
`AppConfig.from_env(env=...)` más `monkeypatch.delenv`, así que el resultado no
depende de lo que haya exportado en la shell quien ejecuta la suite.

### Integraciones

Las de OMDb se omiten solas si `OMDB_API_KEY` no está definida, con un motivo
explícito en el `skipif`. Las de TVMaze no necesitan credencial.

Comprueban presencia y forma, no valores exactos. Un rating o un número de
resultados cambian con cada actualización del catálogo y convertirían la suite
en una fuente de falsos positivos.

### Qué queda sin probar

`ui/menu.py`, al 15%. Es el único módulo con `input()`, y probar cada rama
simulando la entrada estándar aporta poco frente a lo ya cubierto en
`test_validators.py` y `test_library.py`. La lógica de validación que usa ya
tiene tests propios en el módulo que la usa.

## Skills

`.opencode/skills/` contiene tres skills para agentes, con el contenido de esta
refactorización convertido en reglas reutilizables:

| Skill | Qué cubre |
| --- | --- |
| `refactoring` | Globales mutables, división de módulos, `except:` desnudo, type hints, inyección de dependencias. Incluye el script AST de auditoría. |
| `api-integration` | Clientes HTTP, timeouts, traducción de excepciones, validación de contrato, caché de aciertos, y cómo impedir que una credencial llegue al log. |
| `pytest-testing` | Estructura de `tests/`, guarda anti-red, dónde parchear de verdad, fixtures, integraciones que se saltan solas. |

opencode los descubre al arrancar. Si no aparecen, salir y volver a entrar: la
configuración no se recarga en caliente.

Un detalle que la asignación no recogía y que conviene saber: opencode no lee un
`skill.json` con un campo `instructions`. Busca `SKILL.md` con frontmatter YAML
dentro de una carpeta llamada como el skill, y el campo `description` es
obligatorio. Sin él, el skill se filtra y no aparece en la lista.

## Notas

- Las URLs usan `https://`.
- Las exportaciones JSON se escriben en UTF-8 sin escapes ASCII.
- La importación valida el esquema antes de tocar el estado: un archivo
  corrupto deja la biblioteca intacta.
- Los nombres de archivo se validan en la interfaz y otra vez en la biblioteca.
- `.env` no se versiona; `.env.example` sí, y solo contiene nombres.
- `pytest.ini` no fija `-m "not integration"` a propósito: con un marker por
  defecto, `pytest -m integration` tendría que luchar contra él.