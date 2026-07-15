"""Testes de app.core.config.Settings — sobretudo a checagem de segurança
que impede ROOT_DOMAIN=localhost de vazar pra um ambiente com DEBUG=False
(ver docs/tcc/MULTI_TENANCY.md)."""
import pytest

from app.core.config import Settings


def test_root_domain_localhost_com_debug_false_falha_no_boot(monkeypatch):
    monkeypatch.setenv("DEBUG", "False")
    monkeypatch.setenv("ROOT_DOMAIN", "localhost")

    with pytest.raises(RuntimeError, match="ROOT_DOMAIN"):
        Settings()


def test_root_domain_127_0_0_1_com_debug_false_falha_no_boot(monkeypatch):
    monkeypatch.setenv("DEBUG", "False")
    monkeypatch.setenv("ROOT_DOMAIN", "127.0.0.1")

    with pytest.raises(RuntimeError, match="ROOT_DOMAIN"):
        Settings()


def test_root_domain_localtest_me_com_debug_false_falha_no_boot(monkeypatch):
    monkeypatch.setenv("DEBUG", "False")
    monkeypatch.setenv("ROOT_DOMAIN", "localtest.me")

    with pytest.raises(RuntimeError, match="ROOT_DOMAIN"):
        Settings()


def test_root_domain_localhost_com_debug_true_e_permitido(monkeypatch):
    monkeypatch.setenv("DEBUG", "True")
    monkeypatch.setenv("ROOT_DOMAIN", "localhost")

    settings = Settings()
    assert settings.ROOT_DOMAIN == "localhost"


def test_root_domain_localtest_me_com_debug_true_e_permitido(monkeypatch):
    monkeypatch.setenv("DEBUG", "True")
    monkeypatch.setenv("ROOT_DOMAIN", "localtest.me")

    settings = Settings()
    assert settings.ROOT_DOMAIN == "localtest.me"


def test_root_domain_real_com_debug_false_e_permitido(monkeypatch):
    monkeypatch.setenv("DEBUG", "False")
    monkeypatch.setenv("ROOT_DOMAIN", "brickei.com.br")
    # Settings() com DEBUG=False também exige SECURITY_SECRET_KEY etc. pra
    # fazer sentido em produção, mas nada disso é validado no __init__ hoje
    # — só ROOT_DOMAIN é. Não precisa setar os outros pra este teste.

    settings = Settings()
    assert settings.ROOT_DOMAIN == "brickei.com.br"
