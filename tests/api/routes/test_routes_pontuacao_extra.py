"""Testes de Pontuação Extra (docs/PONTUACAO_EXTRA.md): pontos avulsos dados
a um jogador num torneio (trouxe um novato, atuou como juiz, etc.), sempre
somados em `pontuacao_com_regras` — nunca em `pontuacao`. Um jogador que
ainda não estava no torneio ganha uma participação nova na hora — exceto pro
motivo Juiz, que exige o vínculo (tipo=JUIZ) já cadastrado antes na aba
principal do torneio (POST /juizes, testado em test_routes_torneio_juizes.py).
tipo=JUIZ exclui a participação do pareamento de rodadas e do ranking/pódio
DESSE torneio (mas não do ranking geral entre torneios — isso é testado só no
cálculo de `pontuacao_com_regras` em si, que continua igual pra todo mundo)."""

from fastapi.testclient import TestClient

from app.core.db import get_session
from sqlmodel import Session, select

from app.models import (
    Loja,
    Jogador,
    JogadorCriado,
    JogadorTorneioLink,
    LojaJogadorLink,
    Rodada,
    Torneio,
    Usuario,
)
from app.utils.datetimeUtil import data_agora_brasil
from app.utils.Enums import TCG, StatusAprovacaoLoja


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


def _criar_loja_autenticada(client: TestClient, nome: str, email: str, senha: str = "senha123") -> tuple[dict, str]:
    r = client.post(
        "/api/lojas/",
        json={"nome": nome, "endereco": "Rua X, 1", "email": email, "senha": senha},
    )
    assert r.status_code == 200, r.text
    # Loja nasce PENDENTE -- aprova direto no banco pra manter este
    # helper simples pros testes que nao sao sobre o fluxo de aprovacao.
    session = client.app.dependency_overrides[get_session]()
    loja_db = session.get(Loja, r.json()["id"])
    loja_db.status = StatusAprovacaoLoja.APROVADA
    session.commit()
    token = _login(client, email, senha)
    return r.json(), token


def _criar_regra(client: TestClient, headers: dict, **overrides) -> dict:
    payload = {
        "nome": "Regra Padrão",
        "pt_vitoria": 3,
        "pt_derrota": 0,
        "pt_empate": 1,
        "pt_oponente_ganha": 0,
        "pt_oponente_perde": 0,
        "pt_oponente_empate": 0,
        "tcg": "POKEMON",
        **overrides,
    }
    r = client.post("/api/lojas/tipoJogador/", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _criar_torneio(client: TestClient, headers: dict, regra_id: int, **overrides) -> dict:
    payload = {
        "data_planejada": "2026-08-01",
        "jogo": "POKEMON",
        "formato": "PADRAO",
        "vagas": 8,
        "regra_basica_id": regra_id,
        **overrides,
    }
    r = client.post("/api/lojas/torneios/criar", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _criar_jogador_da_loja(session: Session, loja_id: int, nome: str, tcg: TCG = TCG.POKEMON) -> dict:
    """Cria uma conta de jogador real, vinculada à loja (LojaJogadorLink) e
    com um JogadorCriado pro jogo — o mínimo pra aparecer na lista de
    "jogadores disponíveis" de Pontuação Extra sem precisar estar inscrito
    em nenhum torneio ainda."""
    u = Usuario(email=f"{nome.lower().replace(' ', '.')}@gmail.com", tipo="jogador",
                is_active=True, data_cadastro=data_agora_brasil())
    u.set_senha("senha123")
    session.add(u)
    session.commit()
    session.refresh(u)

    j = Jogador(nome=nome, usuario_id=u.id)
    session.add(j)
    session.commit()
    session.refresh(j)

    session.add(LojaJogadorLink(jogador_id=j.id, loja_id=loja_id, apelido=nome))

    jogador_criado = JogadorCriado(game_id=f"gid-{nome.lower().replace(' ', '-')}", tcg=tcg, jogador_id=j.id)
    session.add(jogador_criado)
    session.commit()
    session.refresh(jogador_criado)

    return {"jogador_id": j.id, "jogador_criado_id": jogador_criado.id, "nome": nome}


def _promover_organizador(client: TestClient, headers: dict, jogador_id: int, tcg: str = "POKEMON") -> None:
    r = client.post(
        f"/api/lojas/jogador/{jogador_id}/promover",
        json={"tcg": tcg},
        headers=headers,
    )
    assert r.status_code == 200, r.text


def _cadastrar_juiz(client: TestClient, headers: dict, torneio_id: str, jogador_criado_id: int) -> dict:
    r = client.post(
        f"/api/lojas/torneios/{torneio_id}/juizes",
        json={"jogador_criado_id": jogador_criado_id},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _adicionar_participantes(session: Session, torneio_id: str, nomes: list[str]) -> list[dict]:
    participantes = []
    loja_id = session.get(Torneio, torneio_id).loja_id
    for nome in nomes:
        u = Usuario(email=f"{nome.lower().replace(' ', '.')}@gmail.com", tipo="jogador",
                    is_active=True, data_cadastro=data_agora_brasil())
        u.set_senha("senha123")
        session.add(u)
        session.commit()
        session.refresh(u)

        j = Jogador(nome=nome, usuario_id=u.id)
        session.add(j)
        session.commit()
        session.refresh(j)

        jogador_criado = JogadorCriado(game_id=f"gid-{nome.lower().replace(' ', '-')}", tcg=TCG.POKEMON, jogador_id=j.id)
        session.add(jogador_criado)
        session.commit()
        session.refresh(jogador_criado)

        link = JogadorTorneioLink(
            torneio_id=torneio_id, loja_id=loja_id, jogador_criado_id=jogador_criado.id, apelido=nome,
            pontuacao=0, pontuacao_com_regras=0,
        )
        session.add(link)
        session.commit()
        session.refresh(link)

        participantes.append({"jogador_id": j.id, "jogador_criado_id": jogador_criado.id, "link_id": link.id, "nome": nome})

    return participantes


def test_pontuacao_extra_para_jogador_ja_no_torneio_soma_so_em_pontuacao_com_regras(client: TestClient, session: Session):
    _, token = _criar_loja_autenticada(client, "Loja PE 1", "loja.pe1@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    participante = _adicionar_participantes(session, torneio["id"], ["Alvo"])[0]

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/pontuacao-extra",
        json={
            "jogador_criado_id": participante["jogador_criado_id"],
            "motivo": "NOVATO",
            "descricao": "Trouxe um amigo novo pro torneio",
            "pontos": 2,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["pontos"] == 2
    assert r.json()["motivo"] == "NOVATO"
    assert r.json()["game_id"] == "gid-alvo"

    link = session.get(JogadorTorneioLink, participante["link_id"])
    assert link.pontuacao_com_regras == 2
    assert link.pontuacao == 0
    assert link.tipo == "JOGADOR"


def test_pontuacao_extra_motivo_juiz_exige_juiz_ja_cadastrado_no_torneio(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja PE 2", "loja.pe2@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    juiz = _criar_jogador_da_loja(session, loja["id"], "Juiz Fulano")

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/pontuacao-extra",
        json={
            "jogador_criado_id": juiz["jogador_criado_id"],
            "motivo": "JUIZ",
            "descricao": None,
            "pontos": 5,
        },
        headers=headers,
    )
    assert r.status_code == 400, r.text
    assert "cadastrado como Juiz" in r.json()["detail"]

    assert session.exec(
        select(JogadorTorneioLink).where(
            JogadorTorneioLink.jogador_criado_id == juiz["jogador_criado_id"]
        )
    ).first() is None


def test_pontuacao_extra_motivo_juiz_soma_pontos_para_juiz_ja_cadastrado(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja PE 2b", "loja.pe2b@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    juiz = _criar_jogador_da_loja(session, loja["id"], "Juiz Fulano2")
    _cadastrar_juiz(client, headers, torneio["id"], juiz["jogador_criado_id"])

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/pontuacao-extra",
        json={
            "jogador_criado_id": juiz["jogador_criado_id"],
            "motivo": "JUIZ",
            "descricao": None,
            "pontos": 5,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text

    link = session.exec(
        select(JogadorTorneioLink).where(
            JogadorTorneioLink.jogador_criado_id == juiz["jogador_criado_id"]
        )
    ).first()
    assert link is not None
    assert link.tipo == "JUIZ"
    assert link.pontuacao_com_regras == 5
    assert link.pontuacao == 0


def test_pontuacao_extra_motivo_outros_para_quem_so_e_juiz_soma_na_mesma_linha(
    client: TestClient, session: Session,
):
    """Um jogador só tem UMA linha por torneio (fonte única de verdade):
    dar pontos de motivo OUTROS pra alguém cuja única participação hoje é
    como Juiz soma na MESMA linha — Pontuação Extra nunca muda o papel de
    ninguém (isso só acontece via TorneioService.adicionar_juiz/inscrição),
    então o tipo continua JUIZ."""
    loja, token = _criar_loja_autenticada(client, "Loja PE 2c", "loja.pe2c@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    pessoa = _criar_jogador_da_loja(session, loja["id"], "Pessoa So Juiz")
    _cadastrar_juiz(client, headers, torneio["id"], pessoa["jogador_criado_id"])

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/pontuacao-extra",
        json={
            "jogador_criado_id": pessoa["jogador_criado_id"],
            "motivo": "OUTROS",
            "descricao": "Ajudou em outra frente",
            "pontos": 7,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text

    links = session.exec(
        select(JogadorTorneioLink).where(
            (JogadorTorneioLink.torneio_id == torneio["id"]) &
            (JogadorTorneioLink.jogador_criado_id == pessoa["jogador_criado_id"])
        )
    ).all()
    assert len(links) == 1
    assert links[0].tipo == "JUIZ"
    assert links[0].pontuacao_com_regras == 7


def test_juiz_nao_entra_no_pareamento_de_rodada(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja PE 3", "loja.pe3@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    _adicionar_participantes(session, torneio["id"], ["Jogador A", "Jogador B"])
    juiz = _criar_jogador_da_loja(session, loja["id"], "Juiz Beltrano")
    _cadastrar_juiz(client, headers, torneio["id"], juiz["jogador_criado_id"])

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/pontuacao-extra",
        json={"jogador_criado_id": juiz["jogador_criado_id"], "motivo": "JUIZ", "descricao": None, "pontos": 3},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    pareamento = r.json()

    # 2 jogadores reais => 1 mesa só; o juiz não aparece em nenhuma rodada.
    assert len(pareamento) == 1
    juiz_link = session.exec(
        select(JogadorTorneioLink).where(
            JogadorTorneioLink.jogador_criado_id == juiz["jogador_criado_id"]
        )
    ).first()
    rodadas = session.exec(
        select(Rodada).where(Rodada.torneio_id == torneio["id"])
    ).all()
    for rodada in rodadas:
        assert rodada.jogador1_id != juiz_link.id
        assert rodada.jogador2_id != juiz_link.id


def test_juiz_nao_aparece_no_ranking_do_torneio_mas_pontua(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja PE 4", "loja.pe4@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers, pt_vitoria=3, pt_derrota=0)
    torneio = _criar_torneio(client, headers, regra["id"])
    participantes = _adicionar_participantes(session, torneio["id"], ["Um", "Dois"])
    juiz = _criar_jogador_da_loja(session, loja["id"], "Juiz Ciclano")
    _cadastrar_juiz(client, headers, torneio["id"], juiz["jogador_criado_id"])

    client.post(
        f"/api/lojas/torneios/{torneio['id']}/pontuacao-extra",
        json={"jogador_criado_id": juiz["jogador_criado_id"], "motivo": "JUIZ", "descricao": None, "pontos": 4},
        headers=headers,
    )

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    pareamento = r.json()
    rodada_id = int(list(pareamento.keys())[0])
    mesa = list(pareamento.values())[0][0]
    vencedor_link_id = next(
        p["link_id"] for p in participantes if p["jogador_id"] == mesa["jogador1"]["jogador_id"]
    )

    r = client.put(
        "/api/lojas/torneios/rodadas/finalizar",
        json=[{"id_rodada": rodada_id, "id_vencedor": vencedor_link_id}],
        headers=headers,
    )
    assert r.status_code == 200, r.text
    ranking = r.json()["ranking"]

    # O ranking (get_torneio_top) só tem os 2 jogadores reais — o juiz nunca
    # aparece nele, mesmo tendo ganhado pontos extras.
    assert len(ranking) == 2
    nomes_no_ranking = {item["jogador_nome"] for item in ranking}
    assert "Juiz Ciclano" not in nomes_no_ranking

    # Mas a pontuação extra do juiz continua valendo (só não aparece nesse
    # ranking específico) — isso é o que alimenta o ranking GERAL entre
    # torneios (docs/RANKING.md), fora do escopo deste teste.
    juiz_link = session.exec(
        select(JogadorTorneioLink).where(
            JogadorTorneioLink.jogador_criado_id == juiz["jogador_criado_id"]
        )
    ).first()
    assert juiz_link.pontuacao_com_regras == 4


def test_jogadores_disponiveis_motivo_novato_mostra_so_quem_ja_esta_no_torneio(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja PE 5", "loja.pe5@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])

    participante = _adicionar_participantes(session, torneio["id"], ["Ja No Torneio"])[0]
    registrado = _criar_jogador_da_loja(session, loja["id"], "Registrado Na Loja")
    _promover_organizador(client, headers, registrado["jogador_id"])

    r = client.get(
        f"/api/lojas/torneios/{torneio['id']}/jogadores-disponiveis",
        params={"motivo": "NOVATO"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    ids_disponiveis = {j["id"] for j in r.json()}

    assert participante["jogador_criado_id"] in ids_disponiveis
    assert registrado["jogador_criado_id"] not in ids_disponiveis


def test_jogadores_disponiveis_motivo_juiz_mostra_so_juizes_ja_cadastrados_no_torneio(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja PE 8", "loja.pe8@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])

    participante = _adicionar_participantes(session, torneio["id"], ["Ja No Torneio"])[0]
    organizador = _criar_jogador_da_loja(session, loja["id"], "Organizador Da Loja")
    _promover_organizador(client, headers, organizador["jogador_id"])
    # Organizador da loja, mas ainda NÃO cadastrado como Juiz deste torneio —
    # não deve aparecer aqui (só na lista de organizadores-disponiveis-juiz).
    nao_cadastrado = _criar_jogador_da_loja(session, loja["id"], "Organizador Nao Cadastrado")
    _promover_organizador(client, headers, nao_cadastrado["jogador_id"])
    _cadastrar_juiz(client, headers, torneio["id"], organizador["jogador_criado_id"])

    r = client.get(
        f"/api/lojas/torneios/{torneio['id']}/jogadores-disponiveis",
        params={"motivo": "JUIZ"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    ids_disponiveis = {j["id"] for j in r.json()}

    assert organizador["jogador_criado_id"] in ids_disponiveis
    assert nao_cadastrado["jogador_criado_id"] not in ids_disponiveis
    assert participante["jogador_criado_id"] not in ids_disponiveis


def test_jogadores_disponiveis_motivo_outros_combina_torneio_e_juizes_cadastrados(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja PE 9", "loja.pe9@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])

    participante = _adicionar_participantes(session, torneio["id"], ["Ja No Torneio"])[0]
    organizador = _criar_jogador_da_loja(session, loja["id"], "Organizador Da Loja")
    _promover_organizador(client, headers, organizador["jogador_id"])
    _cadastrar_juiz(client, headers, torneio["id"], organizador["jogador_criado_id"])
    registrado = _criar_jogador_da_loja(session, loja["id"], "Registrado Na Loja")

    r = client.get(
        f"/api/lojas/torneios/{torneio['id']}/jogadores-disponiveis",
        params={"motivo": "OUTROS"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    ids_disponiveis = {j["id"] for j in r.json()}

    assert participante["jogador_criado_id"] in ids_disponiveis
    assert organizador["jogador_criado_id"] in ids_disponiveis
    assert registrado["jogador_criado_id"] not in ids_disponiveis


def test_pontuacao_extra_jogador_de_tcg_diferente_e_rejeitada(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja PE 6", "loja.pe6@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])  # jogo=POKEMON
    jogador_vgc = _criar_jogador_da_loja(session, loja["id"], "Jogador VGC", tcg=TCG.POKEMON_VGC)

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/pontuacao-extra",
        json={"jogador_criado_id": jogador_vgc["jogador_criado_id"], "motivo": "OUTROS", "descricao": None, "pontos": 1},
        headers=headers,
    )
    assert r.status_code == 400


def test_historico_pontuacao_extra_da_loja_filtra_por_tcg(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja PE 7", "loja.pe7@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    participante = _adicionar_participantes(session, torneio["id"], ["Historico"])[0]

    client.post(
        f"/api/lojas/torneios/{torneio['id']}/pontuacao-extra",
        json={"jogador_criado_id": participante["jogador_criado_id"], "motivo": "OUTROS", "descricao": "Ajuda na organização", "pontos": 1},
        headers=headers,
    )

    r = client.get("/api/lojas/pontuacao-extra/", params={"tcg": "POKEMON"}, headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["torneio_nome"] == torneio["nome"]

    r = client.get("/api/lojas/pontuacao-extra/", params={"tcg": "POKEMON_VGC"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == []
