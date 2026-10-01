"""Pruebas de :class:`Session`, el composition root.

Es el unico modulo que sabe como se conectan las piezas, y eso lo hace el lugar
donde un error de cableado pasaria inadvertido: cada servicio con la
configuracion equivocada, o la biblioteca con un tope que no es el pedido.

Dos comportamientos merecen fijarse con test:

* ``rebuild_with`` **conserva la biblioteca** al cambiar la configuracion. Las
  favoritas y el historial son datos del usuario, no ajustes: perderlos al
  cambiar el TTL del menu seria perder trabajo del usuario.
* ``cache_stats`` reconstruye las tres caches con las claves de siempre, que es
  lo que la opcion 8 del menu imprime.

Los servicios se inyectan simulados mediante ``monkeypatch``, de modo que
construir la sesion no abre ninguna conexion.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

import session as session_mod
from cache import TTLCache
from config import AppConfig
from library import MovieLibrary
from services import MovieService, SeriesService
from session import Session
from tests.conftest import FAKE_API_KEY


@pytest.fixture
def servicios_falsos(monkeypatch: pytest.MonkeyPatch) -> dict[str, Mock]:
    """Sustituye las dos clases de servicio por dobles registrables.

    Se parchea en ``session``, que es donde se importan: parchear
    ``services.movie_service.MovieService`` no tendria efecto, porque
    ``session`` ya tiene el nombre resuelto en su namespace.
    """
    peliculas = Mock(spec=MovieService)
    peliculas.movie_cache_stats.return_value = {"entries": 1, "hits": 2, "misses": 3}
    peliculas.local_cache_stats.return_value = {"entries": 4, "hits": 5, "misses": 6}
    peliculas.close.return_value = None

    series = Mock(spec=SeriesService)
    series.series_cache_stats.return_value = {"entries": 7, "hits": 8, "misses": 9}
    series.close.return_value = None

    monkeypatch.setattr(session_mod, "MovieService", Mock(return_value=peliculas))
    monkeypatch.setattr(session_mod, "SeriesService", Mock(return_value=series))
    return {"movies": peliculas, "series": series}


@pytest.fixture
def config_prueba() -> AppConfig:
    return AppConfig(
        omdb_api_key=FAKE_API_KEY,
        request_timeout=5.0,
        max_retries=2,
        cache_ttl_seconds=120,
        cache_max_entries=8,
        max_history_entries=7,
    )


class TestBuild:
    """La construccion del grafo de objetos."""

    def test_construye_una_sesion_completa(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        sesion = Session.build(config_prueba)

        assert isinstance(sesion, Session)
        assert sesion.config is config_prueba
        assert sesion.movies is servicios_falsos["movies"]
        assert sesion.series is servicios_falsos["series"]
        assert isinstance(sesion.library, MovieLibrary)

    def test_pasa_la_configuracion_a_los_servicios(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Cada servicio captura la configuracion al construirse. Si recibiera
        # otra, sus timeouts y sus caches serian distintos de los del menu.
        Movie = session_mod.MovieService
        Series = session_mod.SeriesService

        Session.build(config_prueba)

        Movie.assert_called_once_with(config_prueba)
        Series.assert_called_once_with(config_prueba)
        # Los servicios reales no se construyen: sus clientes abririan sockets,
        # y la guarda anti-red de `conftest` lo impediria.

    def test_la_biblioteca_hereda_el_tope_de_historial(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        # Si el tope no viniera de la configuracion, `MAX_HISTORY_ENTRIES` no
        # tendria efecto y el menu no podria ajustarlo.
        sesion = Session.build(config_prueba)

        assert sesion.library._max_history == 7

    def test_construir_no_consulta_la_red(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        # La guarda anti-red lo verifica: si `build` abriera un socket, este
        # test fallaria aqui mismo.
        assert Session.build(config_prueba) is not None

    def test_registra_la_construccion_sin_filtrar_la_clave(
        self,
        config_prueba: AppConfig,
        servicios_falsos: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        with caplog.at_level(logging.INFO, logger="session"):
            Session.build(config_prueba)

        # El timeout y el TTL si ayudan a depurar; la clave no aparece nunca.
        assert "5.0" in caplog.text
        assert FAKE_API_KEY not in caplog.text


class TestInmutabilidad:
    """``Session`` es ``frozen=True``: un cambio genera otra sesion."""

    def test_no_se_puede_asignar_un_atributo(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        sesion = Session.build(config_prueba)

        with pytest.raises(Exception):
            sesion.config = config_prueba  # type: ignore[misc]


class TestRebuildWith:
    """Cambiar la configuracion sin perder los datos del usuario."""

    def test_devuelve_una_sesion_nueva(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        sesion = Session.build(config_prueba)

        nueva = sesion.rebuild_with(config_prueba.with_timeout(30.0))

        assert nueva is not sesion

    def test_los_servicios_se_reconstruyen(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Los servicios capturan la configuracion al construirse: si no se
        # reconstruyeran, seguirian con el timeout viejo.
        Movie = session_mod.MovieService
        sesion = Session.build(config_prueba)
        Movie.reset_mock()

        sesion.rebuild_with(config_prueba.with_timeout(30.0))

        assert Movie.call_count == 1

    def test_la_biblioteca_se_conserva(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        # La garantia importante: cambiar el TTL desde el menu no puede borrar
        # las favoritas de la persona.
        sesion = Session.build(config_prueba)
        sesion.library.add_favorite({"Title": "Interstellar"})

        nueva = sesion.rebuild_with(config_prueba.with_overrides(cache_ttl_seconds=600))

        assert len(nueva.library.favorites) == 1
        assert nueva.library.favorites[0]["Title"] == "Interstellar"

    def test_el_historial_se_conserva(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        sesion = Session.build(config_prueba)
        sesion.library.add_to_history({"Title": "Interstellar"})

        nueva = sesion.rebuild_with(config_prueba.with_timeout(60.0))

        assert len(nueva.library.history) == 1

    def test_la_configuracion_se_actualiza(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        sesion = Session.build(config_prueba)

        nueva = sesion.rebuild_with(config_prueba.with_timeout(30.0))

        assert nueva.config.request_timeout == 30.0

    def test_cierra_los_servicios_anteriores(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        # Si no, cada cambio de configuracion en el menu dejaria una conexion
        # HTTP abierta.
        sesion = Session.build(config_prueba)

        sesion.rebuild_with(config_prueba.with_timeout(30.0))

        servicios_falsos["movies"].close.assert_called()
        servicios_falsos["series"].close.assert_called()

    def test_registra_el_cambio_de_configuracion(
        self,
        config_prueba: AppConfig,
        servicios_falsos: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        sesion = Session.build(config_prueba)

        with caplog.at_level(logging.INFO, logger="session"):
            sesion.rebuild_with(config_prueba.with_timeout(30.0))

        assert "30.0" in caplog.text
        assert FAKE_API_KEY not in caplog.text


class TestCacheStats:
    """Las tres caches con las claves que espera el menu."""

    def test_devuelve_las_tres_caches(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        sesion = Session.build(config_prueba)

        metricas = sesion.cache_stats()

        # Los nombres exactos son el contrato con la opcion 8 del menu.
        assert set(metricas) == {"movies", "series", "local"}

    def test_consulta_las_caches_de_los_servicios_correctos(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        sesion = Session.build(config_prueba)

        sesion.cache_stats()

        servicios_falsos["movies"].movie_cache_stats.assert_called()
        servicios_falsos["series"].series_cache_stats.assert_called()
        servicios_falsos["movies"].local_cache_stats.assert_called()

    def test_el_catalogo_local_aparece_bajo_clave_local(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        # La cache del catalogo local vive en MovieService, no en SeriesService:
        # por eso su clave es "local" y no "series".
        sesion = Session.build(config_prueba)

        metricas = sesion.cache_stats()

        assert metricas["local"] == {"entries": 4, "hits": 5, "misses": 6}

    def test_devuelve_las_metricas_de_los_servicios(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        sesion = Session.build(config_prueba)

        metricas = sesion.cache_stats()

        assert metricas["movies"] == {"entries": 1, "hits": 2, "misses": 3}
        assert metricas["series"] == {"entries": 7, "hits": 8, "misses": 9}


class TestClose:
    """El cierre de los dos servicios."""

    def test_cierra_ambos_servicios(
        self, config_prueba: AppConfig, servicios_falsos: dict[str, Any]
    ) -> None:
        sesion = Session.build(config_prueba)

        sesion.close()

        servicios_falsos["movies"].close.assert_called_once()
        servicios_falsos["series"].close.assert_called_once()


class TestLasCachesSonInyectables:
    """La razon por la que los tests de TTL son deterministas.

    ``MovieService`` y ``SeriesService`` crean sus caches con el TTL de la
    configuracion, y ambas aceptan un reloj. Este test deja constancia de la
    cadena completa: sin ella, la cache no seria determinista.
    """

    def test_el_servicio_de_peliculas_crea_dos_caches(
        self, config_prueba: AppConfig
    ) -> None:
        from unittest.mock import Mock

        servicio = MovieService(config_prueba, omdb=Mock())

        assert isinstance(servicio._movie_cache, TTLCache)
        assert isinstance(servicio._local_cache, TTLCache)

    def test_las_caches_usan_el_ttl_de_la_configuracion(
        self, config_prueba: AppConfig
    ) -> None:
        from unittest.mock import Mock

        servicio = MovieService(config_prueba, omdb=Mock())

        assert servicio._movie_cache.ttl_seconds == 120.0
        assert servicio._local_cache.ttl_seconds == 120.0

    def test_las_caches_usan_el_tope_de_la_configuracion(
        self, config_prueba: AppConfig
    ) -> None:
        from unittest.mock import Mock

        servicio = MovieService(config_prueba, omdb=Mock())

        assert servicio._movie_cache.max_entries == 8

    def test_el_servicio_de_series_crea_una_cache(
        self, config_prueba: AppConfig
    ) -> None:
        from unittest.mock import Mock

        servicio = SeriesService(config_prueba, tvmaze=Mock())

        assert isinstance(servicio._series_cache, TTLCache)
        assert servicio._series_cache.ttl_seconds == 120.0
