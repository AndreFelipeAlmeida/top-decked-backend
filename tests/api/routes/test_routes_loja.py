from fastapi.testclient import TestClient

from app.core.db import get_session
from app.models import Loja, LojaJogadorLink
from app.utils.Enums import StatusAprovacaoLoja


def _login(client: TestClient, email: str, senha: str) -> str:
    r = client.post("/api/login/token", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    client.cookies.clear()
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


def _criar_jogador_autenticado(client: TestClient, nome: str, email: str, senha: str = "senha123") -> tuple[dict, dict]:
    r = client.post("/api/jogadores/", json={"nome": nome, "email": email, "senha": senha})
    assert r.status_code == 200, r.text
    token = _login(client, email, senha)
    return r.json(), {"Authorization": f"Bearer {token}"}


def test_retornar_lojas_vazio(client: TestClient):
    r = client.get("/api/lojas/")
    assert r.status_code == 200
    assert r.json() == []


def test_retornar_lojas_so_lista_aprovadas(client: TestClient):
    _criar_loja(client, "Loja Aprovada Diretorio", "loja.aprovada.diretorio@gmail.com")

    r = client.post(
        "/api/lojas/",
        json={"nome": "Loja Pendente Diretorio", "email": "loja.pendente.diretorio@gmail.com", "senha": "senha123"},
    )
    assert r.status_code == 200, r.text

    r = client.get("/api/lojas/")
    nomes = [loja["nome"] for loja in r.json()]
    assert "Loja Aprovada Diretorio" in nomes
    assert "Loja Pendente Diretorio" not in nomes


def test_retornar_lojas_sem_login_nao_marca_tcgs_organizados(client: TestClient):
    _criar_loja(client, "Loja Anonima Diretorio", "loja.anonima.diretorio@gmail.com")

    r = client.get("/api/lojas/")
    assert r.status_code == 200
    loja = next(l for l in r.json() if l["nome"] == "Loja Anonima Diretorio")
    assert loja["tcgs_organizados"] == []


def test_retornar_lojas_marca_tcgs_organizados_do_jogador_logado(client: TestClient):
    loja_organizada = _criar_loja(client, "Loja Organizada Diretorio", "loja.organizada.diretorio@gmail.com")
    loja_qualquer = _criar_loja(client, "Loja Qualquer Diretorio", "loja.qualquer.diretorio@gmail.com")
    jogador, headers_jogador = _criar_jogador_autenticado(
        client, "Organizador Diretorio", "organizador.diretorio@gmail.com"
    )

    session = client.app.dependency_overrides[get_session]()
    session.add(LojaJogadorLink(jogador_id=jogador["id"], loja_id=loja_organizada["id"], apelido="Organizador"))
    session.commit()

    token_loja = _login(client, "loja.organizada.diretorio@gmail.com", "senha123")
    r = client.post(
        f"/api/lojas/jogador/{jogador['id']}/promover",
        json={"tcg": "POKEMON"},
        headers={"Authorization": f"Bearer {token_loja}"},
    )
    assert r.status_code == 200, r.text

    r = client.get("/api/lojas/", headers=headers_jogador)
    assert r.status_code == 200
    por_nome = {loja["nome"]: loja for loja in r.json()}
    assert por_nome["Loja Organizada Diretorio"]["tcgs_organizados"] == ["POKEMON"]
    assert por_nome["Loja Qualquer Diretorio"]["tcgs_organizados"] == []
    assert loja_qualquer["nome"] == "Loja Qualquer Diretorio"


def test_criar_loja(client: TestClient):
    data = _criar_loja(client, "Loja Teste", "loja_teste@gmail.com")
    assert data["nome"] == "Loja Teste"
    assert "id" in data
    assert data["usuario"]["email"] == "loja_teste@gmail.com"


def test_criar_loja_gera_slug_a_partir_do_nome(client: TestClient):
    data = _criar_loja(client, "Evolution Games", "evolution.games@gmail.com")
    assert data["slug"] == "evolution-games"


def test_criar_loja_com_nome_acentuado_remove_acentos_do_slug(client: TestClient):
    data = _criar_loja(client, "Ginásio São Paulo", "ginasio.saopaulo@gmail.com")
    assert data["slug"] == "ginasio-sao-paulo"


def test_criar_loja_com_nome_duplicado_gera_slug_com_sufixo_numerico(client: TestClient):
    primeira = _criar_loja(client, "Loja Repetida", "repetida.um@gmail.com")
    segunda = _criar_loja(client, "Loja Repetida", "repetida.dois@gmail.com")
    terceira = _criar_loja(client, "Loja Repetida", "repetida.tres@gmail.com")

    assert primeira["slug"] == "loja-repetida"
    assert segunda["slug"] == "loja-repetida-2"
    assert terceira["slug"] == "loja-repetida-3"


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


def test_atualizar_loja_reenviando_o_proprio_email_nao_acusa_duplicado(client: TestClient):
    _criar_loja(client, "Loja Email Proprio", "loja.email.proprio@gmail.com", "senha123")
    token = _login(client, "loja.email.proprio@gmail.com", "senha123")

    r = client.put(
        "/api/lojas/",
        json={"nome": "Loja Email Proprio", "email": "loja.email.proprio@gmail.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text


def test_atualizar_loja_para_email_de_outra_conta_e_rejeitado(client: TestClient):
    _criar_loja(client, "Loja Email A", "loja.email.a@gmail.com", "senha123")
    _criar_loja(client, "Loja Email B", "loja.email.b@gmail.com", "senha123")
    token = _login(client, "loja.email.b@gmail.com", "senha123")

    r = client.put(
        "/api/lojas/",
        json={"nome": "Loja Email B", "email": "loja.email.a@gmail.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text


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
