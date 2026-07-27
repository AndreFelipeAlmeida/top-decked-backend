from fastapi.testclient import TestClient

from app.core.db import get_session
from app.models import Loja
from app.utils.Enums import StatusAprovacaoLoja


def _login(client: TestClient, email: str, senha: str) -> str:
    r = client.post("/api/login/token", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return r.json()["access_token"]


def _criar_loja_autenticada(client: TestClient, nome: str, email: str, senha: str = "senha123") -> dict:
    payload = {
        "nome": nome,
        "endereco": "Rua Teste, 123",
        "email": email,
        "senha": senha,
    }
    r = client.post("/api/lojas/", json=payload)
    assert r.status_code == 200, r.text
    session = client.app.dependency_overrides[get_session]()
    loja_db = session.get(Loja, r.json()["id"])
    loja_db.status = StatusAprovacaoLoja.APROVADA
    session.commit()

    token = _login(client, email, senha)
    return {**r.json(), "headers": {"Authorization": f"Bearer {token}"}}


def _criar_categoria(client: TestClient, headers: dict, nome: str) -> dict:
    r = client.post("/api/estoque/categoria/", json={"nome": nome}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _criar_item(client: TestClient, headers: dict, categoria_id: int, nome: str = "Booster Box", is_vendavel: bool | None = None) -> dict:
    payload = {
        "nome": nome,
        "categoria": categoria_id,
        "preco": 10.0,
        "quantidade": 5,
        "min_quantidade": 1,
    }
    if is_vendavel is not None:
        payload["is_vendavel"] = is_vendavel
    r = client.post("/api/lojas/item/", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_criar_item_e_vendavel_por_padrao(client: TestClient):
    loja = _criar_loja_autenticada(client, "Loja Estoque", "loja.estoque@gmail.com")
    categoria = _criar_categoria(client, loja["headers"], "Booster Boxes")

    item = _criar_item(client, loja["headers"], categoria["id"])
    assert item["is_vendavel"] is True


def test_atualizar_item_pode_desativar_venda(client: TestClient):
    loja = _criar_loja_autenticada(client, "Loja Estoque Toggle", "loja.estoque.toggle@gmail.com")
    categoria = _criar_categoria(client, loja["headers"], "Premiação")
    item = _criar_item(client, loja["headers"], categoria["id"], nome="Playmat de Premiação")

    r = client.put(
        f"/api/lojas/item/{item['id']}",
        json={
            "nome": item["nome"],
            "categoria": categoria["id"],
            "preco": item["preco"],
            "min_quantidade": item["min_quantidade"],
            "is_vendavel": False,
        },
        headers=loja["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_vendavel"] is False


def test_listar_itens_filtra_apenas_vendaveis(client: TestClient):
    loja = _criar_loja_autenticada(client, "Loja Estoque Filtro", "loja.estoque.filtro@gmail.com")
    categoria = _criar_categoria(client, loja["headers"], "Geral")
    _criar_item(client, loja["headers"], categoria["id"], nome="Booster Vendável", is_vendavel=True)
    _criar_item(client, loja["headers"], categoria["id"], nome="Brinde Interno", is_vendavel=False)

    r = client.get("/api/lojas/item/?apenas_vendaveis=true", headers=loja["headers"])
    assert r.status_code == 200, r.text
    nomes = [item["nome"] for item in r.json()]
    assert nomes == ["Booster Vendável"]

    r = client.get("/api/lojas/item/", headers=loja["headers"])
    assert r.status_code == 200, r.text
    nomes = [item["nome"] for item in r.json()]
    assert set(nomes) == {"Booster Vendável", "Brinde Interno"}


def test_mover_item_para_categoria_de_outra_loja_e_negado(client: TestClient):
    loja_a = _criar_loja_autenticada(client, "Loja A Estoque", "loja.a.estoque@gmail.com")
    loja_b = _criar_loja_autenticada(client, "Loja B Estoque", "loja.b.estoque@gmail.com")

    categoria_a = _criar_categoria(client, loja_a["headers"], "Categoria A")
    categoria_b = _criar_categoria(client, loja_b["headers"], "Categoria B")
    item_a = _criar_item(client, loja_a["headers"], categoria_a["id"])

    r = client.put(
        f"/api/lojas/item/{item_a['id']}",
        json={
            "nome": item_a["nome"],
            "categoria": categoria_b["id"],
            "preco": item_a["preco"],
            "min_quantidade": item_a["min_quantidade"],
        },
        headers=loja_a["headers"],
    )
    assert r.status_code == 404, r.text

    r = client.get(f"/api/lojas/item/{item_a['id']}", headers=loja_a["headers"])
    assert r.json()["categoria"] == categoria_a["id"]


def test_mover_item_para_categoria_da_mesma_loja_funciona(client: TestClient):
    loja = _criar_loja_autenticada(client, "Loja Estoque Mover", "loja.estoque.mover@gmail.com")
    categoria_origem = _criar_categoria(client, loja["headers"], "Origem")
    categoria_destino = _criar_categoria(client, loja["headers"], "Destino")
    item = _criar_item(client, loja["headers"], categoria_origem["id"])

    r = client.put(
        f"/api/lojas/item/{item['id']}",
        json={
            "nome": item["nome"],
            "categoria": categoria_destino["id"],
            "preco": item["preco"],
            "min_quantidade": item["min_quantidade"],
        },
        headers=loja["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["categoria"] == categoria_destino["id"]
