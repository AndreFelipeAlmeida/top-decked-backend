from fastapi.testclient import TestClient
from sqlmodel import Session, select

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
    token = _login(client, "loja_del@gmail.com", "senha123")

    r = client.delete("/api/lojas/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204, r.text

    r = client.get(f"/api/lojas/{criada['id']}")
    assert r.status_code == 404


def test_deletar_loja_sem_autenticacao_e_negado(client: TestClient):
    """Regressão: o endpoint antigo (`DELETE /lojas/{id}`) não exigia
    autenticação nenhuma — qualquer chamada apagava qualquer loja pelo id.
    Agora é sempre a própria loja autenticada se excluindo, sem id na URL."""
    r = client.delete("/api/lojas/")
    assert r.status_code == 401


def test_deletar_loja_apaga_toda_a_cascata(client: TestClient, session: Session):
    from datetime import date

    from app.models import (
        Categoria, Evento, Item, JogadorCriado, JogadorTorneioLink,
        LojaJogadorLink, LojaJogadorOrganizadorTCG, Rodada, Temporada,
        TipoJogador, Torneio, Usuario, Jogador,
    )
    from app.utils.Enums import TCG
    from app.utils.datetimeUtil import data_agora_brasil

    criada = _criar_loja(client, "Loja Cascata", "loja.cascata@gmail.com")
    loja_id = criada["id"]
    token = _login(client, "loja.cascata@gmail.com", "senha123")

    regra = TipoJogador(
        nome="Regra", pt_vitoria=3, pt_derrota=0, pt_empate=1,
        pt_oponente_perde=0, pt_oponente_ganha=0, pt_oponente_empate=0,
        tcg="POKEMON", loja_id=loja_id,
    )
    session.add(regra)
    session.commit()
    session.refresh(regra)

    torneio = Torneio(
        loja_id=loja_id, jogo=TCG.POKEMON, tipo="CRIADO",
        data_planejada=date(2026, 8, 1), regra_basica_id=regra.id,
    )
    session.add(torneio)
    session.commit()
    session.refresh(torneio)

    usuario = Usuario(email="jogador.cascata@gmail.com", tipo="jogador",
                      is_active=True, data_cadastro=data_agora_brasil())
    usuario.set_senha("senha123")
    session.add(usuario)
    session.commit()
    session.refresh(usuario)
    jogador = Jogador(nome="Jogador Cascata", usuario_id=usuario.id)
    session.add(jogador)
    session.commit()
    session.refresh(jogador)
    jogador_criado = JogadorCriado(game_id="gid-cascata", tcg=TCG.POKEMON, jogador_id=jogador.id)
    session.add(jogador_criado)
    session.commit()
    session.refresh(jogador_criado)

    link = JogadorTorneioLink(
        torneio_id=torneio.id, loja_id=loja_id, jogador_criado_id=jogador_criado.id, apelido="Jogador Cascata",
    )
    session.add(link)
    session.commit()
    session.refresh(link)

    rodada = Rodada(torneio_id=torneio.id, loja_id=loja_id, num_rodada=1,
                    jogador1_id=link.id, jogador2_id=None, vencedor_id=link.id, finalizada=True)
    session.add(rodada)

    evento = Evento(loja_id=loja_id, tcg=TCG.POKEMON, nome="Evento Cascata",
                    data_inicio=date(2026, 8, 1), data_fim=date(2026, 8, 31))
    session.add(evento)

    loja_jogador_link = LojaJogadorLink(jogador_id=jogador.id, loja_id=loja_id, creditos=10)
    session.add(loja_jogador_link)
    session.commit()
    session.refresh(loja_jogador_link)
    session.add(LojaJogadorOrganizadorTCG(loja_jogador_link_id=loja_jogador_link.id, tcg=TCG.POKEMON))

    categoria = Categoria(loja_id=loja_id, nome="Categoria Cascata")
    session.add(categoria)
    session.commit()
    session.refresh(categoria)
    session.add(Item(loja_id=loja_id, nome="Item Cascata", categoria=categoria.id, preco=10))

    session.add(Temporada(tcg=TCG.POKEMON, loja_id=loja_id, ano_inicio=2026, mes_inicio=1, ano_fim=2026, mes_fim=12))

    session.commit()

    # Capturados antes do delete: os objetos Python ficam desanexados da
    # session logo abaixo, e ler um atributo deles depois disso explodiria
    # com DetachedInstanceError em vez de simplesmente devolver o valor.
    torneio_id = torneio.id
    loja_jogador_link_id = loja_jogador_link.id
    jogador_id = jogador.id
    jogador_criado_id = jogador_criado.id
    usuario_id = criada["usuario"]["id"]

    r = client.delete("/api/lojas/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204, r.text

    # A cascata roda em SQL puro (não via session.delete()), então os
    # objetos já carregados acima continuam presos ao identity map da
    # session -- session.get() para um deles explodiria com
    # ObjectDeletedError (em vez de devolver None) se não forem desanexados
    # primeiro, já que expirá-los ainda tenta (e falha) recarregá-los.
    session.expunge_all()

    assert session.get(Torneio, torneio_id) is None
    assert session.exec(select(Rodada).where(Rodada.loja_id == loja_id)).first() is None
    assert session.exec(select(JogadorTorneioLink).where(JogadorTorneioLink.loja_id == loja_id)).first() is None
    assert session.exec(select(Evento).where(Evento.loja_id == loja_id)).first() is None
    assert session.exec(select(LojaJogadorLink).where(LojaJogadorLink.loja_id == loja_id)).first() is None
    assert session.exec(
        select(LojaJogadorOrganizadorTCG).where(LojaJogadorOrganizadorTCG.loja_jogador_link_id == loja_jogador_link_id)
    ).first() is None
    assert session.exec(select(Categoria).where(Categoria.loja_id == loja_id)).first() is None
    assert session.exec(select(Item).where(Item.loja_id == loja_id)).first() is None
    assert session.exec(select(TipoJogador).where(TipoJogador.loja_id == loja_id)).first() is None
    assert session.exec(select(Temporada).where(Temporada.loja_id == loja_id)).first() is None
    assert session.get(Loja, loja_id) is None
    assert session.get(Usuario, usuario_id) is None

    # O jogador (conta, JogadorCriado, histórico de torneio) não é tocado --
    # excluir uma loja nunca deve apagar dados que pertencem ao jogador.
    assert session.get(Jogador, jogador_id) is not None
    assert session.get(JogadorCriado, jogador_criado_id) is not None
