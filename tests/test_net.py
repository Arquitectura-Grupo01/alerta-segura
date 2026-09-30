import socket

import pytest

from core.net import DestinoBloqueado, ip_es_publica, resolver_y_validar

BLOQUEADAS = [
    "127.0.0.1",          # loopback
    "10.0.0.5",           # privada
    "172.16.3.4",         # privada
    "192.168.1.1",        # privada
    "169.254.169.254",    # metadata de nube (AWS, GCP, Azure)
    "100.64.0.1",         # CGNAT
    "0.0.0.0",            # "esta red"
    "224.0.0.1",          # multicast
    "::1",                # loopback IPv6
    "fe80::1",            # link-local IPv6
    "fc00::1",            # ULA IPv6 (privada)
    "::ffff:127.0.0.1",   # loopback disfrazado de IPv6
    "::ffff:169.254.169.254",
    "no-es-una-ip",
]
PERMITIDAS = ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"]


@pytest.mark.parametrize("ip", BLOQUEADAS)
def test_bloquea_redes_internas(ip):
    assert ip_es_publica(ip) is False


@pytest.mark.parametrize("ip", PERMITIDAS)
def test_permite_ips_publicas(ip):
    assert ip_es_publica(ip) is True


def _fake_getaddrinfo(ips):
    def _f(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]
    return _f


def test_rechaza_si_alguna_ip_es_privada(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        _fake_getaddrinfo(["8.8.8.8", "10.0.0.1"]))
    with pytest.raises(DestinoBloqueado):
        resolver_y_validar("mixto.example")


def test_acepta_si_todas_son_publicas(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        _fake_getaddrinfo(["8.8.8.8", "1.1.1.1"]))
    assert resolver_y_validar("ok.example") == ["1.1.1.1", "8.8.8.8"]


def test_host_que_no_resuelve(monkeypatch):
    def _falla(*a, **k):
        raise socket.gaierror("no resuelve")
    monkeypatch.setattr(socket, "getaddrinfo", _falla)
    with pytest.raises(DestinoBloqueado):
        resolver_y_validar("inexistente.example")
