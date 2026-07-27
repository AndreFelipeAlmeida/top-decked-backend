from fastapi.testclient import TestClient
from sqlmodel import Session, select


def _login(client: TestClient, email: str, senha: str) -> str:
    r = client.post("/api/login/token", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
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

    r = client.put(
        "/api/jogadores/",
        json={"nome": "Ana Atualizada", "tcgs": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "Ana Atualizada"


def test_atualizar_jogador_reenviando_o_proprio_email_nao_acusa_duplicado(client: TestClient) -> None:
    _criar_jogador(client, "Bia", "bia.email@gmail.com", "senha123")
    token = _login(client, "bia.email@gmail.com", "senha123")

    r = client.put(
        "/api/jogadores/",
        json={"nome": "Bia", "email": "bia.email@gmail.com", "tcgs": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text


def test_atualizar_jogador_para_email_de_outra_conta_e_rejeitado(client: TestClient) -> None:
    _criar_jogador(client, "Caio", "caio.email@gmail.com", "senha123")
    _criar_jogador(client, "Duda", "duda.email@gmail.com", "senha123")
    token = _login(client, "duda.email@gmail.com", "senha123")

    r = client.put(
        "/api/jogadores/",
        json={"nome": "Duda", "email": "caio.email@gmail.com", "tcgs": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text


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

    # Exclusão total agora: o Jogador (e a conta de login) somem de vez.
    r = client.get(f"/api/jogadores/{criado['id']}")
    assert r.status_code == 404

    # A conta apagada não consegue mais logar.
    r = client.post("/api/login/token", data={"username": "bruno@gmail.com", "password": "senha123"})
    assert r.status_code in (400, 401)


def test_deletar_jogador_anonimiza_em_vez_de_apagar_jogadorcriado(client: TestClient, session: Session) -> None:
    """Créditos (LojaJogadorLink), organização e conquistas são apagados de
    vez -- mas JogadorCriado (a identidade dentro do TCG, com o histórico de
    torneios já disputados) só perde a referência ao jogador (jogador_id
    vira NULL), nunca é apagado."""
    from app.models import (
        Conquista, HistoricoConquista, JogadorConquista, JogadorCriado,
        LojaJogadorLink, LojaJogadorOrganizadorTCG, Loja, Usuario,
    )
    from app.utils.Enums import CategoriaConquista, StatusAprovacaoLoja, TCG
    from app.utils.datetimeUtil import data_agora_brasil

    criado = _criar_jogador(client, "Eva", "eva.anonimizada@gmail.com", "senha123")
    token = _login(client, "eva.anonimizada@gmail.com", "senha123")
    jogador_id = criado["id"]

    jogador_criado = JogadorCriado(game_id="gid-eva-anonimizada", tcg=TCG.POKEMON, jogador_id=jogador_id)
    session.add(jogador_criado)
    session.commit()
    session.refresh(jogador_criado)
    jogador_criado_id = jogador_criado.id

    usuario_loja = Usuario(email="loja.anonimizacao@gmail.com", tipo="loja", is_active=True,
                           data_cadastro=data_agora_brasil())
    usuario_loja.set_senha("senha123")
    session.add(usuario_loja)
    session.commit()
    session.refresh(usuario_loja)
    loja = Loja(nome="Loja Anonimizacao", usuario_id=usuario_loja.id,
               status=StatusAprovacaoLoja.APROVADA, slug="loja-anonimizacao")
    session.add(loja)
    session.commit()
    session.refresh(loja)

    link = LojaJogadorLink(jogador_id=jogador_id, loja_id=loja.id, creditos=50)
    session.add(link)
    session.commit()
    session.refresh(link)
    session.add(LojaJogadorOrganizadorTCG(loja_jogador_link_id=link.id, tcg=TCG.POKEMON))

    conquista = Conquista(codigo="TESTE_ANONIMIZACAO", nome="Teste", descricao="Teste",
                          categoria=CategoriaConquista.TORNEIOS_JOGADOS, icone="🏆", tcg=TCG.POKEMON)
    session.add(conquista)
    session.commit()
    session.refresh(conquista)

    session.add(JogadorConquista(jogador_id=jogador_id, conquista_id=conquista.id, progresso_atual=5, nivel_atual=1))
    session.add(HistoricoConquista(jogador_id=jogador_id, conquista_id=conquista.id, nivel=1, progresso_no_momento=5))
    session.commit()

    # Capturado antes do delete -- ver comentário equivalente no teste de
    # cascata de exclusão de loja (test_routes_loja.py).
    link_id = link.id

    r = client.delete(f"/api/jogadores/{jogador_id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204, r.text

    session.expunge_all()

    assert session.get(JogadorCriado, jogador_criado_id).jogador_id is None
    assert session.exec(select(LojaJogadorLink).where(LojaJogadorLink.jogador_id == jogador_id)).first() is None
    assert session.exec(
        select(LojaJogadorOrganizadorTCG).where(LojaJogadorOrganizadorTCG.loja_jogador_link_id == link_id)
    ).first() is None
    assert session.exec(select(JogadorConquista).where(JogadorConquista.jogador_id == jogador_id)).first() is None
    assert session.exec(select(HistoricoConquista).where(HistoricoConquista.jogador_id == jogador_id)).first() is None


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
