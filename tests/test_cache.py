"""El caché de respuestas no crece sin límite."""

from app.core import cache


def test_cache_is_bounded(monkeypatch):
    cache.clear_response_cache()
    monkeypatch.setattr(cache, "MAX_CACHE_ENTRIES", 3)
    for i in range(10):
        cache.set_cached_response(f"k{i}", i)
    assert len(cache._RESPONSE_CACHE) == 3
    assert cache.get_cached_response("k9") == 9  # lo más nuevo se conserva
    assert cache.get_cached_response("k0") is None  # lo más viejo se descarta
    cache.clear_response_cache()
