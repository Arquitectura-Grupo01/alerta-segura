import re

import pytest
from django.urls import reverse


def test_respuestas_llevan_csp_sin_unsafe_inline(client):
    csp = client.get("/health/").headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp


def test_csp_tambien_en_errores(client):
    assert "Content-Security-Policy" in client.post("/health/").headers


@pytest.mark.django_db
def test_login_del_admin_no_usa_scripts_en_linea(client):
    # La CSP bloquea scripts en línea. Si una versión nueva de Django los agrega
    # al admin, la consola dejaría de funcionar en producción.
    html = client.get(reverse("admin:login")).content.decode()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html, re.IGNORECASE)
