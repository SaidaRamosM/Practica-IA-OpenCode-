"""Pruebas de :class:`TTLCache`: caducidad por tiempo y expulsion LRU.

Es la pieza que evita que cada pulsacion del menu consuma cuota de la API, asi
que sus garantias --no caducar antes de tiempo, cachear lo que toca, expulsar la
menos usada y no cachear errores-- estan fijadas aqui.

Todos los tests usan el ``reloj_falso`` de ``conftest.py``, inyectado por el
parametro ``clock`` que ``TTLCache`` ya tenia. Sin el, cada test de caducidad
tendria que esperar de verdad, y la suite seria lenta y poco fiable.
"""

from __future__ import annotations

from typing import Any

import pytest

from cache import CacheStats, TTLCache


@pytest.fixture
def cache(reloj_falso: Any) -> TTLCache[str]:
    """Cache de 2 entradas, TTL de 10 s, con reloj controlable."""
    return TTLCache(10.0, max_entries=2, clock=reloj_falso)


class TestOperacionesBasicas:
    """Guardar y recuperar."""

    def test_una_clave_ausente_devuelve_none(self, cache: TTLCache[str]) -> None:
        assert cache.get("inexistente") is None

    def test_guarda_y_recupera_un_valor(self, cache: TTLCache[str]) -> None:
        cache.set("k", "valor")

        assert cache.get("k") == "valor"

    def test_un_segundo_set_sobreescribe_el_valor(
        self, cache: TTLCache[str]
    ) -> None:
        cache.set("k", "primero")
        cache.set("k", "segundo")

        assert cache.get("k") == "segundo"

    def test_admite_valores_falsy(self, cache: TTLCache[Any]) -> None:
        # `get` devuelve `None` como senal de "no hay". Si 0, "" o [] se
        # confundieran con ausencia, habria que reconsultar la API sin motivo.
        for valor in (0, "", [], False):
            cache2 = TTLCache(10.0, max_entries=2, clock=cache._clock)
            cache2.set("k", valor)

            assert cache2.get("k") == valor
            assert cache2.get("k") is not None

    def test_invalidate_devuelve_true_si_existia(
        self, cache: TTLCache[str]
    ) -> None:
        cache.set("k", "valor")

        assert cache.invalidate("k") is True

    def test_invalidate_devuelve_false_si_no_existia(
        self, cache: TTLCache[str]
    ) -> None:
        assert cache.invalidate("inexistente") is False

    def test_una_clave_invalidate_ya_no_se_encuentra(
        self, cache: TTLCache[str]
    ) -> None:
        cache.set("k", "valor")
        cache.invalidate("k")

        assert cache.get("k") is None

    def test_clear_vacia_todas_las_claves(self, cache: TTLCache[str]) -> None:
        cache.set("a", "1")
        cache.set("b", "2")

        cache.clear()

        assert len(cache) == 0
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_clear_conserva_las_metricas(self, cache: TTLCache[str]) -> None:
        # Son acumuladas de la sesion: borrarlas haria perder de golpe todo lo
        # que muestra la pantalla de estadisticas.
        cache.set("k", "valor")
        cache.get("k")

        cache.clear()

        assert cache.stats().hits == 1


class TestCaducidad:
    """La parte de reloj, que es donde un ``sleep`` arruinaria los tests."""

    def test_el_valor_sigue_disponible_antes_del_ttl(
        self, cache: TTLCache[str], reloj_falso: Any
    ) -> None:
        cache.set("k", "valor")
        reloj_falso.avanza(9.9)

        assert cache.get("k") == "valor"

    def test_el_valor_caduca_al_llegar_al_ttl(
        self, cache: TTLCache[str], reloj_falso: Any
    ) -> None:
        # Frontera inclusiva: a los 10 s exactos ya no vale. `>=` y no `>`.
        cache.set("k", "valor")
        reloj_falso.avanza(10.0)

        assert cache.get("k") is None

    def test_la_lectura_de_un_caducado_lo_descarta(
        self, cache: TTLCache[str], reloj_falso: Any
    ) -> None:
        # No hace falta un proceso de barrido: leerlo ya lo elimina, de modo
        # que una entrada caducada no ocupa sitio para siempre.
        cache.set("k", "valor")
        reloj_falso.avanza(11)

        cache.get("k")

        assert len(cache) == 0

    def test_caducar_cuenta_como_expiracion_y_como_fallo(
        self, cache: TTLCache[str], reloj_falso: Any
    ) -> None:
        # Es un fallo para quien consulta (no hay dato) y una expiracion para
        # quien mantiene (habia algo y se ha ido). Las dos cifras se necesitan
        # en la pantalla de estadisticas.
        cache.set("k", "valor")
        reloj_falso.avanza(11)

        cache.get("k")

        metricas = cache.stats()
        assert metricas.expirations == 1
        assert metricas.misses == 1

    def test_un_set_renueva_el_ttl(
        self, cache: TTLCache[str], reloj_falso: Any
    ) -> None:
        # Volver a escribir la clave reinicia la cuenta atras. Sin esto, un
        # refresco a mitad de vida no serviria de nada.
        cache.set("k", "valor")
        reloj_falso.avanza(8)
        cache.set("k", "valor")
        reloj_falso.avanza(8)

        assert cache.get("k") == "valor"

    def test_purge_expired_retira_las_caducadas(
        self, cache: TTLCache[str], reloj_falso: Any
    ) -> None:
        cache.set("vieja", "1")
        reloj_falso.avanza(11)
        cache.set("nueva", "2")

        retiradas = cache.purge_expired()

        assert retiradas == 1
        assert cache.get("vieja") is None
        assert cache.get("nueva") == "2"

    def test_purge_expired_no_toca_las_vigentes(self, cache: TTLCache[str]) -> None:
        cache.set("k", "valor")

        assert cache.purge_expired() == 0
        assert cache.get("k") == "valor"

    def test_acepta_un_ttl_decimal(self, reloj_falso: Any) -> None:
        # 0.1 s es un TTL legitimo para pruebas de cache en caliente.
        cache = TTLCache(0.1, clock=reloj_falso)
        cache.set("k", "valor")
        reloj_falso.avanza(0.2)

        assert cache.get("k") is None


class TestEviccionLru:
    """La segunda garantia: la cache no crece sin limite."""

    def test_no_expulsa_mientras_haya_hueco(
        self, cache: TTLCache[str]
    ) -> None:
        cache.set("a", "1")
        cache.set("b", "2")

        assert cache.stats().evictions == 0
        assert len(cache) == 2

    def test_expulsa_la_menos_usada_al_superar_el_tope(
        self, cache: TTLCache[str]
    ) -> None:
        # con max_entries=2, la tercera entrada obliga a tirar la primera.
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("c", "3")

        assert len(cache) == 2
        assert cache.get("a") is None
        assert cache.get("b") == "2"
        assert cache.get("c") == "3"

    def test_leer_una_clave_la_protege_de_la_expulsion(
        self, cache: TTLCache[str]
    ) -> None:
        # "LRU" significa "menos usada", no "mas antigua": leer "a" la sube en
        # el orden y es "b" la que se va.
        cache.set("a", "1")
        cache.set("b", "2")
        cache.get("a")
        cache.set("c", "3")

        assert cache.get("a") == "1"
        assert cache.get("b") is None

    def test_reescribir_una_clave_tambien_la_protege(
        self, cache: TTLCache[str]
    ) -> None:
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("a", "1 actualizado")
        cache.set("c", "3")

        assert cache.get("a") == "1 actualizado"
        assert cache.get("b") is None

    def test_la_expulsion_se_cuenta_en_las_metricas(
        self, cache: TTLCache[str]
    ) -> None:
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("c", "3")

        assert cache.stats().evictions == 1

    def test_avisa_por_log_al_expulsar(
        self, cache: TTLCache[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        # Una expulsion es una consulta que se pierde, no un fallo de la cache:
        # por eso es WARNING y no ERROR. Si bajara a ERROR, saltaria como error
        # de aplicacion en la pantalla.
        import logging

        with caplog.at_level(logging.WARNING, logger="cache"):
            cache.set("a", "1")
            cache.set("b", "2")
            cache.set("c", "3")

        assert cache.stats().evictions == 1
        assert any(record.levelno == logging.WARNING for record in caplog.records)
        assert not any(record.levelno >= logging.ERROR for record in caplog.records)

    def test_expulsa_hasta_respetar_el_tope(
        self, reloj_falso: Any
    ) -> None:
        # Insertar de golpe mas entradas de las que caben tiene que dejar la
        # cache en su limite, no en un estado intermedio.
        cache = TTLCache(10.0, max_entries=2, clock=reloj_falso)

        for indice in range(10):
            cache.set(f"k{indice}", str(indice))

        assert len(cache) == 2
        assert cache.stats().evictions == 8


class TestMetricas:
    """Lo que muestra la opcion 8 del menu."""

    def test_empieza_a_cero(self, cache: TTLCache[str]) -> None:
        metricas = cache.stats()

        assert metricas.entries == 0
        assert metricas.hits == 0
        assert metricas.misses == 0

    def test_cuenta_aciertos_y_fallos(self, cache: TTLCache[str]) -> None:
        cache.set("k", "valor")
        cache.get("k")
        cache.get("k")
        cache.get("otra")

        metricas = cache.stats()
        assert metricas.hits == 2
        assert metricas.misses == 1

    def test_el_tasa_de_aciertos_evita_la_division_por_cero(
        self, cache: TTLCache[str]
    ) -> None:
        # Sin esto, el menu 8 reventaria en la primera consulta de la sesion.
        assert cache.stats().hit_rate == 0.0

    def test_la_tasa_de_aciertos_es_la_proporcion_correcta(
        self, cache: TTLCache[str]
    ) -> None:
        cache.set("k", "valor")
        cache.get("k")
        cache.get("otra")

        assert cache.stats().hit_rate == 0.5

    def test_as_dict_expone_las_mismas_claves(
        self, cache: TTLCache[str]
    ) -> None:
        # La pantalla de estadisticas depende de estos nombres exactos.
        datos = cache.stats().as_dict()

        assert set(datos) == {
            "entries",
            "hits",
            "misses",
            "expirations",
            "evictions",
            "hit_rate",
        }

    def test_reset_stats_pone_los_contadores_a_cero(
        self, cache: TTLCache[str]
    ) -> None:
        cache.set("k", "valor")
        cache.get("k")
        cache.get("otra")

        cache.reset_stats()

        metricas = cache.stats()
        assert metricas.hits == 0
        assert metricas.misses == 0

    def test_reset_stats_no_toca_las_entradas(
        self, cache: TTLCache[str]
    ) -> None:
        # Separar "reiniciar los contadores" de "vaciar la cache" permite
        # medir un intervalo concreto sin perder lo cacheado.
        cache.set("k", "valor")

        cache.reset_stats()

        assert cache.get("k") == "valor"

    def test_as_dict_redondea_la_tasa(
        self, cache: TTLCache[str]
    ) -> None:
        # 1 de 3 = 0.3333: se redondea a 4 decimales para que la pantalla no
        # muestre una ristra de ceros.
        cache.set("k", "valor")
        cache.get("k")
        cache.get("otra")
        cache.get("otra2")

        assert cache.stats().as_dict()["hit_rate"] == 0.3333


class TestIntrospeccion:
    """``len``, ``in`` e iteracion."""

    def test_len_refleja_las_entradas(self, cache: TTLCache[str]) -> None:
        cache.set("a", "1")
        cache.set("b", "2")

        assert len(cache) == 2

    def test_in_una_clave_presente(self, cache: TTLCache[str]) -> None:
        cache.set("k", "valor")

        assert "k" in cache

    def test_in_una_clave_ausente(self, cache: TTLCache[str]) -> None:
        assert "inexistente" not in cache

    def test_in_una_clave_caducada_es_falso(
        self, cache: TTLCache[str], reloj_falso: Any
    ) -> None:
        # `in` consulta la caducidad sin contar como acierto ni como fallo: es
        # una pregunta, no una lectura de valor.
        cache.set("k", "valor")
        reloj_falso.avanza(11)

        assert "k" not in cache

    def test_in_no_altera_las_metricas(self, cache: TTLCache[str]) -> None:
        cache.set("k", "valor")

        "k" in cache
        "inexistente" in cache

        metricas = cache.stats()
        assert metricas.hits == 0
        assert metricas.misses == 0

    def test_in_con_un_tipo_no_valido_es_falso(
        self, cache: TTLCache[str]
    ) -> None:
        # Las claves son cadenas: preguntar por un int no debe reventar.
        cache.set("k", "valor")

        assert 123 not in cache

    def test_iterar_devuelve_las_claves(
        self, cache: TTLCache[str]
    ) -> None:
        cache.set("a", "1")
        cache.set("b", "2")

        assert set(cache) == {"a", "b"}

    def test_iterar_no_falla_si_la_cache_se_modifica_durante(
        self, cache: TTLCache[str]
    ) -> None:
        # Se itera sobre una copia: si no, un `for k in cache` que escriba
        # reventaria con "dictionary changed size during iteration".
        cache.set("a", "1")

        for clave in cache:
            cache.set(f"{clave}-copia", "2")

        assert "a-copia" in cache

    def test_el_repr_muestra_tamano_y_limites(
        self, cache: TTLCache[str]
    ) -> None:
        cache.set("k", "valor")

        representacion = repr(cache)

        assert "TTLCache" in representacion
        assert "size=1" in representacion
        assert "max_entries=2" in representacion

    def test_expone_su_ttl_y_su_tope(
        self, cache: TTLCache[str]
    ) -> None:
        assert cache.ttl_seconds == 10.0
        assert cache.max_entries == 2


class TestValidacionDelConstructor:
    """Un valor imposible se rechaza al construir, no al usar."""

    @pytest.mark.parametrize("ttl", [0, -1, -0.5])
    def test_rechaza_un_ttl_no_positivo(self, ttl: float) -> None:
        # Un TTL de 0 cachearia sin cachear, y un negativo la vaciaria siempre.
        with pytest.raises(ValueError, match="ttl_seconds"):
            TTLCache(ttl)

    @pytest.mark.parametrize("max_entries", [0, -1])
    def test_rechaza_un_tope_no_positivo(self, max_entries: int) -> None:
        with pytest.raises(ValueError, match="max_entries"):
            TTLCache(10.0, max_entries=max_entries)

    def test_rechaza_un_reloj_que_no_se_puede_llamar(self) -> None:
        # Sin esta comprobacion, el fallo apareceria en la primera lectura, con
        # un mensaje que no diria nada del reloj.
        with pytest.raises(TypeError, match="clock"):
            TTLCache(10.0, clock="no-soy-una-funcion")  # type: ignore[arg-type]

    def test_acepta_el_reloj_por_defecto(self) -> None:
        # `monotonic` es el correcto: un reloj que se ajusta hacia atras
        # (el del sistema) haria caducar entradas antes de tiempo.
        assert TTLCache(10.0).ttl_seconds == 10.0


class TestCacheStats:
    """El contenedor de metricas, por si alguien lo usa directamente."""

    def test_escribe_todas_las_cifras(self) -> None:
        metricas = CacheStats(entries=2, hits=3, misses=1, expirations=0, evictions=0)

        assert metricas.as_dict()["entries"] == 2
        assert metricas.as_dict()["hits"] == 3

    def test_sin_consultas_la_tasa_es_cero(self) -> None:
        assert CacheStats(0, 0, 0, 0, 0).hit_rate == 0.0
