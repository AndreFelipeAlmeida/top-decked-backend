from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, senha: str) -> str:
    r = client.post("/api/login/token", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    # BRK-309: login agora tambem seta cookies de sessao no TestClient (que
    # mantem um cookie jar persistente, como um browser de verdade) -- sem
    # limpar aqui, chamadas seguintes que passam Authorization no header
    # explicitamente ainda carregariam o cookie da ULTIMA conta logada
    # (silenciosamente autenticando como a pessoa errada quando um teste usa
    # duas contas no mesmo client). Os testes deste arquivo sao sobre regras
    # de negocio, nao sobre a sessao via cookie em si (isso tem suite propria
    # em test_routes_login.py) -- por isso aqui a autenticacao volta a
    # depender só do header, como antes do BRK-309.
    client.cookies.clear()
    return r.json()["access_token"]


def _criar_jogador(client: TestClient, nome: str, email: str, senha: str = "senha123") -> dict:
    r = client.post("/api/jogadores/", json={"nome": nome, "email": email, "senha": senha})
    assert r.status_code == 200, r.text
    return r.json()


def test_retornar_jogadores_vazio(client: TestClient) -> None:
    r = client.get("/api/jogadores/")
    assert r.status_code == 200
    data = r.json()
    # GET /jogadores/ é paginado (PaginatedJogadores), não devolve uma lista crua.
    assert data["data"] == []
    assert data["total"] == 0
    assert data["page"] == 1


def test_criar_jogador(client: TestClient) -> None:
    data = _criar_jogador(client, "João", "joao@gmail.com")
    assert data["nome"] == "João"
    assert "id" in data
    assert data["usuario"]["email"] == "joao@gmail.com"


def test_criar_jogador_email_duplicado(client: TestClient) -> None:
    payload = {"nome": "Maria", "email": "maria@gmail.com", "senha": "senha123"}
    client.post("/api/jogadores/", json=payload)
    r = client.post("/api/jogadores/", json=payload)
    assert r.status_code == 400
    assert "email cadastrado" in r.json()["detail"]


def test_ler_jogador_por_id(client: TestClient) -> None:
    criado = _criar_jogador(client, "Carlos", "carlos@gmail.com")

    r = client.get(f"/api/jogadores/{criado['id']}")
    assert r.status_code == 200
    assert r.json()["nome"] == "Carlos"


def test_ler_jogador_inexistente(client: TestClient) -> None:
    r = client.get("/api/jogadores/9999")
    assert r.status_code == 404


def test_atualizar_jogador_autenticado(client: TestClient) -> None:
    _criar_jogador(client, "Ana", "ana@gmail.com", "senha123")
    token = _login(client, "ana@gmail.com", "senha123")

    # PUT /jogadores/ atualiza o PRÓPRIO jogador autenticado (não recebe id na
    # URL) — `tcgs` precisa ser enviado (mesmo que null) porque o schema
    # `JogadorUpdate` não tinha default antes (ver docs/DIVIDA_TECNICA.md).
    r = client.put(
        "/api/jogadores/",
        json={"nome": "Ana Atualizada", "tcgs": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "Ana Atualizada"


def test_data_nascimento_nao_perde_um_dia_ao_salvar(client: TestClient) -> None:
    """Regressão: Jogador.data_nascimento já foi DateTime(timezone=True) —
    o mesmo bug de Torneio.data_planejada, que podia gravar/ler o dia
    errado dependendo do fuso. Salvar 01/01 (a data mais sensível a esse
    tipo de deslocamento) precisa continuar sendo 01/01 na leitura."""
    _criar_jogador(client, "Nascimento Exato", "nascimentoexato@gmail.com", "senha123")
    token = _login(client, "nascimentoexato@gmail.com", "senha123")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.put(
        "/api/jogadores/",
        json={"nome": "Nascimento Exato", "data_nascimento": "2010-01-01", "tcgs": None},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data_nascimento"] == "2010-01-01"

    r = client.get("/api/jogadores/me", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["data_nascimento"] == "2010-01-01"


def test_atualizar_jogador_sem_autenticacao_e_negado(client: TestClient) -> None:
    r = client.put("/api/jogadores/", json={"nome": "Sem Auth"})
    assert r.status_code == 401


def test_deletar_jogador_autenticado(client: TestClient) -> None:
    criado = _criar_jogador(client, "Bruno", "bruno@gmail.com", "senha123")
    token = _login(client, "bruno@gmail.com", "senha123")

    r = client.delete(
        f"/api/jogadores/{criado['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204

    # "Deletar" só apaga o Usuario (a conta de login) — o Jogador em si (e seu
    # histórico de torneios/links) continua existindo, só sem usuário
    # vinculado. Ver `delete_usuario` em app/api/routes/jogador.py.
    r = client.get(f"/api/jogadores/{criado['id']}")
    assert r.status_code == 200
    assert r.json()["usuario"] is None


def test_deletar_jogador_de_outra_conta_e_negado(client: TestClient) -> None:
    vitima = _criar_jogador(client, "Vítima", "vitima@gmail.com", "senha123")
    _criar_jogador(client, "Atacante", "atacante@gmail.com", "senha123")
    token_atacante = _login(client, "atacante@gmail.com", "senha123")

    # O jogador autenticado (atacante) tenta deletar a conta de OUTRO jogador
    # (vítima) pelo id — a rota checa posse via usuario_id do token, não deve
    # deixar passar.
    r = client.delete(
        f"/api/jogadores/{vitima['id']}",
        headers={"Authorization": f"Bearer {token_atacante}"},
    )
    assert r.status_code == 403

    # A vítima continua existindo.
    r = client.get(f"/api/jogadores/{vitima['id']}")
    assert r.status_code == 200
