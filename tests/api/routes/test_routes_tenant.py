"""Testes de GET /tenant/atual (BRK-308): o endpoint público que o
frontend consulta no boot da SPA pra saber em qual loja (se alguma) o
subdomínio atual está travado. Igual a test_tenant_host_middleware.py, o
caso de subdomínio conhecido precisa de uma app isolada com
`TenantHostMiddleware` apontando pro banco de teste via `session_factory`
— o middleware roda fora da injeção de dependência do FastAPI, então não
enxerga `app.dependency_overrides` do `client`/`session` compartilhados."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.routes import tenant
from app.core.db import get_session
from app.middleware.TenantHostMiddleware import TenantHostMiddleware
from app.models import Loja, Usuario
from app.utils.Enums import StatusAprovacaoLoja
from app.utils.datetimeUtil import data_agora_brasil

ROOT_DOMAIN = "brickei.com.br"


def _montar_client_de_teste(session: Session) -> TestClient:
    app = FastAPI()
    app.include_router(tenant.router)
    app.dependency_overrides[get_session] = lambda: session
    app.add_middleware(
        TenantHostMiddleware,
        root_domain=ROOT_DOMAIN,
        session_factory=lambda: session,
    )
    return TestClient(app)


def _criar_loja(session: Session, nome: str, slug: str) -> Loja:
    usuario = Usuario(email=f"{slug}@gmail.com", tipo="loja", is_active=True, data_cadastro=data_agora_brasil())
    usuario.set_senha("senha123")
    session.add(usuario)
    session.commit()
    session.refresh(usuario)

    loja = Loja(nome=nome, usuario_id=usuario.id, status=StatusAprovacaoLoja.APROVADA, slug=slug)
    session.add(loja)
    session.commit()
    session.refresh(loja)
    return loja


def test_tenant_atual_no_dominio_raiz_retorna_none(client, session: Session):
    """`client` (fixture principal, ver tests/conftest.py) usa o Host
    padrão do TestClient ("testserver"), que não bate com ROOT_DOMAIN nem
    com nenhum subdomínio dele — cai em modo global sem nunca precisar
    tocar o banco (por isso não precisa da app isolada aqui)."""
    r = client.get("/api/tenant/atual")
    assert r.status_code == 200
    assert r.json() is None


def test_tenant_atual_em_subdominio_de_loja_retorna_dados_publicos(session: Session):
    loja = _criar_loja(session, "Evolution Games", "evolution-games")
    client = _montar_client_de_teste(session)

    r = client.get("/tenant/atual", headers={"Host": f"evolution-games.{ROOT_DOMAIN}"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["id"] == loja.id
    assert corpo["nome"] == "Evolution Games"
    assert corpo["slug"] == "evolution-games"


def test_tenant_atual_em_subdominio_inexistente_e_404(session: Session):
    client = _montar_client_de_teste(session)
    r = client.get("/tenant/atual", headers={"Host": f"naoexiste.{ROOT_DOMAIN}"})
    assert r.status_code == 404
