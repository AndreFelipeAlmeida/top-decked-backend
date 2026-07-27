"""Testes do CRUD dinâmico de entidades do Admin focados nos bugs
do Bug Bash da Sprint 7."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.db import get_session
from app.models import Administrador, Usuario
from app.utils.datetimeUtil import data_agora_brasil


def _login(client: TestClient, email: str, senha: str) -> str:
    r = client.post("/api/login/token", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return r.json()["access_token"]


def _sessao_do_client(client: TestClient) -> Session:
    return client.app.dependency_overrides[get_session]()


def _criar_admin_autenticado(client: TestClient, email: str, senha: str = "senha-admin-123") -> dict:
    session = _sessao_do_client(client)
    usuario = Usuario(email=email, tipo="admin", is_active=True, data_cadastro=data_agora_brasil())
    usuario.set_senha(senha)
    session.add(usuario)
    session.commit()
    session.refresh(usuario)

    admin = Administrador(nome="Admin Teste", usuario_id=usuario.id)
    session.add(admin)
    session.commit()

    token = _login(client, email, senha)
    return {"Authorization": f"Bearer {token}"}


def _criar_jogador(client: TestClient, nome: str, email: str, senha: str = "senha123") -> dict:
    r = client.post("/api/jogadores/", json={"nome": nome, "email": email, "senha": senha})
    assert r.status_code == 200, r.text
    return r.json()


def _criar_loja_autenticada(client: TestClient, nome: str, email: str, senha: str = "senha123") -> dict:
    from app.models import Loja
    from app.utils.Enums import StatusAprovacaoLoja

    r = client.post(
        "/api/lojas/",
        json={"nome": nome, "endereco": "Rua X, 1", "email": email, "senha": senha},
    )
    assert r.status_code == 200, r.text
    session = _sessao_do_client(client)
    loja_db = session.get(Loja, r.json()["id"])
    loja_db.status = StatusAprovacaoLoja.APROVADA
    session.commit()
    token = _login(client, email, senha)
    return {**r.json(), "headers": {"Authorization": f"Bearer {token}"}}


def test_deletar_jogador_com_vinculo_de_credito_nao_quebra_com_integrity_error(client: TestClient):
    admin_headers = _criar_admin_autenticado(client, "admin.cascade@brickei.com.br")
    jogador = _criar_jogador(client, "Jogador Cascade", "jogador.cascade@gmail.com")
    loja = _criar_loja_autenticada(client, "Loja Cascade", "loja.cascade@gmail.com")

    r = client.post(
        f"/api/creditos/{jogador['id']}",
        params={"apelido": "Apelido Cascade"},
        headers=loja["headers"],
    )
    assert r.status_code == 200, r.text

    r = client.delete(f"/api/admin/entidades/jogador/{jogador['id']}", headers=admin_headers)
    assert r.status_code == 204, r.text

    r = client.get("/api/creditos/", headers=loja["headers"])
    assert r.status_code in (200, 404)
    vinculos = r.json() if r.status_code == 200 else []
    assert all(v["jogador_id"] != jogador["id"] for v in vinculos)
