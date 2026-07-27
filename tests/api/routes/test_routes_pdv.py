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


def _criar_jogador_autenticado(client: TestClient, nome: str, email: str, senha: str = "senha123") -> dict:
    r = client.post("/api/jogadores/", json={"nome": nome, "email": email, "senha": senha})
    assert r.status_code == 200, r.text
    token = _login(client, email, senha)
    return {**r.json(), "headers": {"Authorization": f"Bearer {token}"}}


def _criar_categoria(client: TestClient, headers: dict, nome: str) -> dict:
    r = client.post("/api/estoque/categoria/", json={"nome": nome}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _criar_item(client: TestClient, headers: dict, categoria_id: int, nome: str, preco: float, quantidade: int, is_vendavel: bool = True) -> dict:
    payload = {
        "nome": nome,
        "categoria": categoria_id,
        "preco": preco,
        "quantidade": quantidade,
        "min_quantidade": 0,
        "is_vendavel": is_vendavel,
    }
    r = client.post("/api/lojas/item/", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _vincular_jogador(client: TestClient, loja_headers: dict, jogador_id: int, apelido: str = "Comprador") -> dict:
    r = client.post(
        f"/api/creditos/{jogador_id}",
        params={"apelido": apelido},
        headers=loja_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _adicionar_credito(client: TestClient, loja_headers: dict, credito_id: int, valor: float) -> dict:
    r = client.patch(
        f"/api/creditos/{credito_id}/adicionar-credito",
        json={"novos_creditos": valor},
        headers=loja_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_checkout_sem_creditos_debita_estoque_e_cobra_tudo_em_dinheiro(client: TestClient):
    loja = _criar_loja_autenticada(client, "Loja PDV", "loja.pdv@gmail.com")
    categoria = _criar_categoria(client, loja["headers"], "Boosters")
    item = _criar_item(client, loja["headers"], categoria["id"], "Booster Pack", preco=10.0, quantidade=5)

    r = client.post(
        "/api/lojas/pdv/checkout",
        json={"itens": [{"item_id": item["id"], "quantidade": 2}], "abater_creditos": False},
        headers=loja["headers"],
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 20.0
    assert data["credito_utilizado"] == 0.0
    assert data["valor_pago_dinheiro"] == 20.0

    r = client.get(f"/api/lojas/item/{item['id']}", headers=loja["headers"])
    assert r.json()["quantidade"] == 3


def test_checkout_abate_credito_parcial_quando_saldo_menor_que_total(client: TestClient):
    loja = _criar_loja_autenticada(client, "Loja PDV Credito", "loja.pdv.credito@gmail.com")
    jogador = _criar_jogador_autenticado(client, "Jogador PDV", "jogador.pdv@gmail.com")
    vinculo = _vincular_jogador(client, loja["headers"], jogador["id"])
    _adicionar_credito(client, loja["headers"], vinculo["id"], 15.0)

    categoria = _criar_categoria(client, loja["headers"], "Boosters")
    item = _criar_item(client, loja["headers"], categoria["id"], "Booster Pack", preco=10.0, quantidade=5)

    r = client.post(
        "/api/lojas/pdv/checkout",
        json={
            "jogador_id": jogador["id"],
            "itens": [{"item_id": item["id"], "quantidade": 3}],
            "abater_creditos": True,
        },
        headers=loja["headers"],
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 30.0
    assert data["credito_utilizado"] == 15.0
    assert data["saldo_credito_restante"] == 0.0
    assert data["valor_pago_dinheiro"] == 15.0

    r = client.get("/api/creditos/", headers=loja["headers"])
    creditos = next(c for c in r.json() if c["jogador_id"] == jogador["id"])
    assert creditos["creditos"] == 0.0


def test_checkout_credito_maior_que_total_zera_valor_em_dinheiro_e_mantem_sobra(client: TestClient):
    loja = _criar_loja_autenticada(client, "Loja PDV Sobra", "loja.pdv.sobra@gmail.com")
    jogador = _criar_jogador_autenticado(client, "Jogador Sobra", "jogador.sobra@gmail.com")
    vinculo = _vincular_jogador(client, loja["headers"], jogador["id"])
    _adicionar_credito(client, loja["headers"], vinculo["id"], 100.0)

    categoria = _criar_categoria(client, loja["headers"], "Boosters")
    item = _criar_item(client, loja["headers"], categoria["id"], "Booster Pack", preco=10.0, quantidade=5)

    r = client.post(
        "/api/lojas/pdv/checkout",
        json={
            "jogador_id": jogador["id"],
            "itens": [{"item_id": item["id"], "quantidade": 2}],
            "abater_creditos": True,
        },
        headers=loja["headers"],
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 20.0
    assert data["credito_utilizado"] == 20.0
    assert data["saldo_credito_restante"] == 80.0
    assert data["valor_pago_dinheiro"] == 0.0


def test_checkout_rejeita_estoque_insuficiente_e_nao_altera_nada(client: TestClient):
    loja = _criar_loja_autenticada(client, "Loja PDV Insuficiente", "loja.pdv.insuf@gmail.com")
    categoria = _criar_categoria(client, loja["headers"], "Boosters")
    item = _criar_item(client, loja["headers"], categoria["id"], "Booster Pack", preco=10.0, quantidade=1)

    r = client.post(
        "/api/lojas/pdv/checkout",
        json={"itens": [{"item_id": item["id"], "quantidade": 5}], "abater_creditos": False},
        headers=loja["headers"],
    )
    assert r.status_code == 400, r.text

    r = client.get(f"/api/lojas/item/{item['id']}", headers=loja["headers"])
    assert r.json()["quantidade"] == 1


def test_checkout_rejeita_item_marcado_como_uso_interno(client: TestClient):
    loja = _criar_loja_autenticada(client, "Loja PDV Interno", "loja.pdv.interno@gmail.com")
    categoria = _criar_categoria(client, loja["headers"], "Premiacao")
    item = _criar_item(client, loja["headers"], categoria["id"], "Playmat Premiação", preco=50.0, quantidade=5, is_vendavel=False)

    r = client.post(
        "/api/lojas/pdv/checkout",
        json={"itens": [{"item_id": item["id"], "quantidade": 1}], "abater_creditos": False},
        headers=loja["headers"],
    )
    assert r.status_code == 400, r.text


def test_checkout_rejeita_item_de_outra_loja(client: TestClient):
    loja_a = _criar_loja_autenticada(client, "Loja PDV A", "loja.pdv.a@gmail.com")
    loja_b = _criar_loja_autenticada(client, "Loja PDV B", "loja.pdv.b@gmail.com")
    categoria_b = _criar_categoria(client, loja_b["headers"], "Boosters B")
    item_b = _criar_item(client, loja_b["headers"], categoria_b["id"], "Item da Loja B", preco=10.0, quantidade=5)

    r = client.post(
        "/api/lojas/pdv/checkout",
        json={"itens": [{"item_id": item_b["id"], "quantidade": 1}], "abater_creditos": False},
        headers=loja_a["headers"],
    )
    assert r.status_code == 404, r.text
