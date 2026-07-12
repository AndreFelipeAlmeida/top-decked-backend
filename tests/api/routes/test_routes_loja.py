from fastapi.testclient import TestClient

from app.core.db import get_session
from app.models import Loja
from app.utils.Enums import StatusAprovacaoLoja


def _login(client: TestClient, email: str, senha: str) -> str:
    r = client.post("/api/login/token", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _criar_loja(client: TestClient, nome: str, email: str, senha: str = "senha123") -> dict:
    payload = {
        "nome": nome,
        "endereco": "Rua Teste, 123",
        "email": email,
        "senha": senha,
    }
    r = client.post("/api/lojas/", json=payload)
    assert r.status_code == 200, r.text
    # Loja nasce PENDENTE -- aprova direto no banco pra manter este helper
    # simples pros testes que não são sobre o fluxo de aprovação em si.
    session = client.app.dependency_overrides[get_session]()
    loja_db = session.get(Loja, r.json()["id"])
    loja_db.status = StatusAprovacaoLoja.APROVADA
    session.commit()
    return r.json()


def test_retornar_lojas_vazio(client: TestClient):
    r = client.get("/api/lojas/")
    assert r.status_code == 200
    assert r.json() == []


def test_criar_loja(client: TestClient):
    data = _criar_loja(client, "Loja Teste", "loja_teste@gmail.com")
    assert data["nome"] == "Loja Teste"
    assert "id" in data
    assert data["usuario"]["email"] == "loja_teste@gmail.com"


def test_criar_loja_email_duplicado(client: TestClient):
    payload = {
        "nome": "Loja Duplicada",
        "endereco": "Rua Duplicada, 456",
        "email": "loja_dup@gmail.com",
        "senha": "senha123",
    }
    client.post("/api/lojas/", json=payload)
    r = client.post("/api/lojas/", json=payload)
    assert r.status_code == 400
    assert "email cadastrado" in r.json()["detail"]


def test_buscar_loja_por_id(client: TestClient):
    criada = _criar_loja(client, "Loja Para Buscar", "loja_busca@gmail.com")

    r = client.get(f"/api/lojas/{criada['id']}")
    assert r.status_code == 200
    assert r.json()["nome"] == "Loja Para Buscar"


def test_buscar_loja_inexistente(client: TestClient):
    r = client.get("/api/lojas/999999")
    assert r.status_code == 404
    assert "não encontrada" in r.json()["detail"].lower()


def test_atualizar_loja_autenticada(client: TestClient):
    _criar_loja(client, "Loja Atualizar", "loja_update@gmail.com", "senha123")
    token = _login(client, "loja_update@gmail.com", "senha123")

    # PUT /lojas/ atualiza a PRÓPRIA loja autenticada (sem id na URL) — não é
    # mais PATCH /lojas/{id} sem autenticação como nas versões antigas da API.
    r = client.put(
        "/api/lojas/",
        json={"nome": "Loja Atualizada", "endereco": "Rua Atualizada, 321"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["nome"] == "Loja Atualizada"
    assert data["endereco"] == "Rua Atualizada, 321"


def test_atualizar_loja_sem_autenticacao_e_negado(client: TestClient):
    r = client.put("/api/lojas/", json={"nome": "Sem Auth"})
    assert r.status_code == 401


def test_deletar_loja(client: TestClient):
    criada = _criar_loja(client, "Loja Deletar", "loja_del@gmail.com")

    r = client.delete(f"/api/lojas/{criada['id']}")
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    r = client.get(f"/api/lojas/{criada['id']}")
    assert r.status_code == 404


def test_deletar_loja_inexistente(client: TestClient):
    r = client.delete("/api/lojas/999999")
    assert r.status_code == 404
