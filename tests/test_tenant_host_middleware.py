from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlmodel import Session
from typing import Annotated

from app.dependencies import contexto_dominio
from app.middleware.TenantHostMiddleware import TenantHostMiddleware
from app.models import Loja, Usuario
from app.utils.Enums import StatusAprovacaoLoja
from app.utils.datetimeUtil import data_agora_brasil


ROOT_DOMAIN = "brickei.com.br"


def _montar_client_de_teste(session: Session) -> TestClient:
    app = FastAPI()

    @app.get("/contexto")
    def get_contexto(loja_id: Annotated[int | None, Depends(contexto_dominio)]):
        return {"loja_id": loja_id}

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


def test_dominio_raiz_e_modo_global(session: Session):
    client = _montar_client_de_teste(session)
    r = client.get("/contexto", headers={"Host": ROOT_DOMAIN})
    assert r.status_code == 200
    assert r.json()["loja_id"] is None


def test_host_sem_relacao_com_root_domain_e_modo_global(session: Session):
    """Host que não é o domínio raiz nem um subdomínio dele (ex.: acesso
    direto por IP/hostname de infra) não é tecnicamente "um subdomínio
    inexistente" — não pode virar 404, só cai pra modo global."""
    client = _montar_client_de_teste(session)
    r = client.get("/contexto", headers={"Host": "192.168.0.10"})
    assert r.status_code == 200
    assert r.json()["loja_id"] is None


def test_subdominio_de_loja_existente_trava_o_contexto(session: Session):
    loja = _criar_loja(session, "Evolution Games", "evolution-games")
    client = _montar_client_de_teste(session)

    r = client.get("/contexto", headers={"Host": f"evolution-games.{ROOT_DOMAIN}"})
    assert r.status_code == 200
    assert r.json()["loja_id"] == loja.id


def test_subdominio_inexistente_e_rejeitado_com_404_antes_de_rotear(session: Session):
    client = _montar_client_de_teste(session)
    r = client.get("/contexto", headers={"Host": f"naoexiste.{ROOT_DOMAIN}"})
    assert r.status_code == 404
    assert r.json()["detail"] == "Loja não encontrada"


def test_www_e_tratado_como_modo_global(session: Session):
    client = _montar_client_de_teste(session)
    r = client.get("/contexto", headers={"Host": f"www.{ROOT_DOMAIN}"})
    assert r.status_code == 200
    assert r.json()["loja_id"] is None


def test_resolucao_de_slug_e_cacheada(session: Session):
    """A segunda requisição pro mesmo subdomínio não pode bater no banco de
    novo dentro do TTL — simulado aqui verificando que trocar o slug da
    loja no banco DEPOIS da primeira resolução não muda o resultado da
    segunda chamada (só o valor cacheado é usado)."""
    loja = _criar_loja(session, "Loja Cache", "loja-cache")
    client = _montar_client_de_teste(session)

    primeira = client.get("/contexto", headers={"Host": f"loja-cache.{ROOT_DOMAIN}"})
    assert primeira.json()["loja_id"] == loja.id

    loja.slug = "loja-cache-renomeada"
    session.add(loja)
    session.commit()

    segunda = client.get("/contexto", headers={"Host": f"loja-cache.{ROOT_DOMAIN}"})
    assert segunda.status_code == 200
    assert segunda.json()["loja_id"] == loja.id
