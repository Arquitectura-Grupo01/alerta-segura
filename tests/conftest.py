import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def cache_limpia():
    """La caché de los tests vive en el proceso: sin esto, los contadores del rate limit
    de un test se arrastrarían al siguiente."""
    cache.clear()
    yield
    cache.clear()
