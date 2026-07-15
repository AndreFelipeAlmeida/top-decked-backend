"""Testes do cadastro oficial de Juízes num torneio (JogadorTorneioLink com
tipo=JUIZ criado via POST /juizes, na aba principal do torneio) — o Juiz
precisa existir aqui antes de poder receber Pontuação Extra com motivo Juiz
(ver test_routes_pontuacao_extra.py). Um jogador só tem UMA linha por
torneio (fonte única de verdade): virar Juiz quando já é Jogador (ou
vice-versa) é upsert pra JOGADOR_E_JUIZ, nunca uma segunda linha."""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.db import get_session
from app.models import (
    Jogador,
    JogadorCriado,
    JogadorTorneioLink,
    Loja,
    LojaJogadorLink,
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


def test_cadastrar_juiz_cria_link_com_tipo_juiz(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja Juiz 1", "loja.juiz1@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    juiz = _criar_jogador_da_loja(session, loja["id"], "Juiz Um")

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/juizes",
        json={"jogador_criado_id": juiz["jogador_criado_id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["tipo"] == "JUIZ"
    assert r.json()["jogador_criado_id"] == juiz["jogador_criado_id"]

    link = session.exec(
        select(JogadorTorneioLink).where(
            JogadorTorneioLink.jogador_criado_id == juiz["jogador_criado_id"]
        )
    ).first()
    assert link is not None
    assert link.tipo == "JUIZ"
    assert link.pontuacao_com_regras == 0


def test_cadastrar_juiz_duplicado_e_rejeitado(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja Juiz 2", "loja.juiz2@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    juiz = _criar_jogador_da_loja(session, loja["id"], "Juiz Dois")

    client.post(
        f"/api/lojas/torneios/{torneio['id']}/juizes",
        json={"jogador_criado_id": juiz["jogador_criado_id"]},
        headers=headers,
    )
    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/juizes",
        json={"jogador_criado_id": juiz["jogador_criado_id"]},
        headers=headers,
    )
    assert r.status_code == 400, r.text
    assert "já está cadastrado como Juiz" in r.json()["detail"]


def test_cadastrar_juiz_jogador_ja_inscrito_como_jogador_vira_jogador_e_juiz(client: TestClient, session: Session):
    """Upsert: já ser Jogador no torneio NÃO bloqueia virar Juiz também — a
    MESMA linha vira tipo=JOGADOR_E_JUIZ, nunca uma segunda."""
    loja, token = _criar_loja_autenticada(client, "Loja Juiz 3", "loja.juiz3@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    jogador = _criar_jogador_da_loja(session, loja["id"], "Jogador Comum")
    session.add(JogadorTorneioLink(
        torneio_id=torneio["id"], loja_id=torneio["loja"]["id"], jogador_criado_id=jogador["jogador_criado_id"],
        apelido=jogador["nome"], tipo="JOGADOR", pontuacao=0, pontuacao_com_regras=4,
    ))
    session.commit()

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/juizes",
        json={"jogador_criado_id": jogador["jogador_criado_id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["tipo"] == "JOGADOR_E_JUIZ"

    links = session.exec(
        select(JogadorTorneioLink).where(
            (JogadorTorneioLink.torneio_id == torneio["id"]) &
            (JogadorTorneioLink.jogador_criado_id == jogador["jogador_criado_id"])
        )
    ).all()
    assert len(links) == 1
    assert links[0].tipo == "JOGADOR_E_JUIZ"
    # Upsert não mexe na pontuação já existente.
    assert links[0].pontuacao_com_regras == 4


def test_cadastrar_juiz_de_quem_ja_e_jogador_e_juiz_e_rejeitado(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja Juiz 3b", "loja.juiz3b@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    jogador = _criar_jogador_da_loja(session, loja["id"], "Jogador Duplo")
    session.add(JogadorTorneioLink(
        torneio_id=torneio["id"], loja_id=torneio["loja"]["id"], jogador_criado_id=jogador["jogador_criado_id"],
        apelido=jogador["nome"], tipo="JOGADOR_E_JUIZ", pontuacao=0, pontuacao_com_regras=0,
    ))
    session.commit()

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/juizes",
        json={"jogador_criado_id": jogador["jogador_criado_id"]},
        headers=headers,
    )
    assert r.status_code == 400, r.text
    assert "já está cadastrado como Juiz" in r.json()["detail"]


def test_cadastrar_juiz_de_tcg_diferente_e_rejeitado(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja Juiz 4", "loja.juiz4@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])  # jogo=POKEMON
    juiz_vgc = _criar_jogador_da_loja(session, loja["id"], "Juiz VGC", tcg=TCG.POKEMON_VGC)

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/juizes",
        json={"jogador_criado_id": juiz_vgc["jogador_criado_id"]},
        headers=headers,
    )
    assert r.status_code == 400, r.text


def test_remover_juiz_que_so_e_juiz_deleta_a_linha(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja Juiz 5", "loja.juiz5@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    juiz = _criar_jogador_da_loja(session, loja["id"], "Juiz Cinco")

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/juizes",
        json={"jogador_criado_id": juiz["jogador_criado_id"]},
        headers=headers,
    )
    link_id = r.json()["id"]

    r = client.delete(f"/api/lojas/torneios/{torneio['id']}/juizes/{link_id}", headers=headers)
    assert r.status_code == 200, r.text

    assert session.get(JogadorTorneioLink, link_id) is None


def test_remover_juiz_que_tambem_e_jogador_faz_downgrade_sem_deletar(client: TestClient, session: Session):
    """Downgrade: remover o papel de Juiz de quem é JOGADOR_E_JUIZ não
    deleta a linha — só volta pra JOGADOR, preservando a participação como
    jogador (pontuação, composição, etc.)."""
    loja, token = _criar_loja_autenticada(client, "Loja Juiz 5b", "loja.juiz5b@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    pessoa = _criar_jogador_da_loja(session, loja["id"], "Duplo Papel Downgrade")
    link = JogadorTorneioLink(
        torneio_id=torneio["id"], loja_id=torneio["loja"]["id"], jogador_criado_id=pessoa["jogador_criado_id"],
        apelido=pessoa["nome"], tipo="JOGADOR_E_JUIZ", pontuacao=0, pontuacao_com_regras=9,
    )
    session.add(link)
    session.commit()
    session.refresh(link)

    r = client.delete(f"/api/lojas/torneios/{torneio['id']}/juizes/{link.id}", headers=headers)
    assert r.status_code == 200, r.text

    session.expire_all()
    link_atualizado = session.get(JogadorTorneioLink, link.id)
    assert link_atualizado is not None
    assert link_atualizado.tipo == "JOGADOR"
    assert link_atualizado.pontuacao_com_regras == 9


def test_remover_juiz_inexistente_e_404(client: TestClient):
    _, token = _criar_loja_autenticada(client, "Loja Juiz 6", "loja.juiz6@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])

    r = client.delete(f"/api/lojas/torneios/{torneio['id']}/juizes/999999", headers=headers)
    assert r.status_code == 404, r.text


def test_organizadores_disponiveis_juiz_exclui_ja_cadastrados(client: TestClient, session: Session):
    loja, token = _criar_loja_autenticada(client, "Loja Juiz 7", "loja.juiz7@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])

    ja_juiz = _criar_jogador_da_loja(session, loja["id"], "Ja Juiz")
    _promover_organizador(client, headers, ja_juiz["jogador_id"])
    ainda_nao = _criar_jogador_da_loja(session, loja["id"], "Ainda Nao Juiz")
    _promover_organizador(client, headers, ainda_nao["jogador_id"])

    client.post(
        f"/api/lojas/torneios/{torneio['id']}/juizes",
        json={"jogador_criado_id": ja_juiz["jogador_criado_id"]},
        headers=headers,
    )

    r = client.get(f"/api/lojas/torneios/{torneio['id']}/organizadores-disponiveis-juiz", headers=headers)
    assert r.status_code == 200, r.text
    ids_disponiveis = {j["id"] for j in r.json()}

    assert ainda_nao["jogador_criado_id"] in ids_disponiveis
    assert ja_juiz["jogador_criado_id"] not in ids_disponiveis


def test_cadastro_de_juiz_requer_autenticacao(client: TestClient):
    r = client.post("/api/lojas/torneios/qualquer-id/juizes", json={"jogador_criado_id": 1})
    assert r.status_code == 401, r.text


def test_jogador_vira_tambem_juiz_no_mesmo_torneio_upsert(client: TestClient, session: Session):
    """Upsert: virar Juiz não bloqueia (nem é bloqueado por) já ser Jogador
    no mesmo torneio — a MESMA linha vira JOGADOR_E_JUIZ, nunca uma
    segunda."""
    loja, token_loja = _criar_loja_autenticada(client, "Loja Juiz 8", "loja.juiz8@gmail.com")
    headers_loja = {"Authorization": f"Bearer {token_loja}"}
    regra = _criar_regra(client, headers_loja)
    torneio = _criar_torneio(client, headers_loja, regra["id"])

    pessoa = _criar_jogador_da_loja(session, loja["id"], "Pessoa Dupla Funcao")
    token_pessoa = _login(client, "pessoa.dupla.funcao@gmail.com", "senha123")
    headers_pessoa = {"Authorization": f"Bearer {token_pessoa}"}

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/juizes",
        json={"jogador_criado_id": pessoa["jogador_criado_id"]},
        headers=headers_loja,
    )
    assert r.status_code == 200, r.text

    r = client.post(f"/api/lojas/torneios/{torneio['id']}/inscricao", headers=headers_pessoa)
    assert r.status_code == 200, r.text
    assert r.json()["tipo"] == "JOGADOR_E_JUIZ"

    links = session.exec(
        select(JogadorTorneioLink).where(
            (JogadorTorneioLink.torneio_id == torneio["id"]) &
            (JogadorTorneioLink.jogador_criado_id == pessoa["jogador_criado_id"])
        )
    ).all()
    assert len(links) == 1
    assert links[0].tipo == "JOGADOR_E_JUIZ"


def test_inscricao_duplicada_como_jogador_ainda_e_rejeitada(client: TestClient, session: Session):
    loja, token_loja = _criar_loja_autenticada(client, "Loja Juiz 9", "loja.juiz9@gmail.com")
    headers_loja = {"Authorization": f"Bearer {token_loja}"}
    regra = _criar_regra(client, headers_loja)
    torneio = _criar_torneio(client, headers_loja, regra["id"])

    _criar_jogador_da_loja(session, loja["id"], "Pessoa Repetida")
    token_pessoa = _login(client, "pessoa.repetida@gmail.com", "senha123")
    headers_pessoa = {"Authorization": f"Bearer {token_pessoa}"}

    r = client.post(f"/api/lojas/torneios/{torneio['id']}/inscricao", headers=headers_pessoa)
    assert r.status_code == 200, r.text

    r = client.post(f"/api/lojas/torneios/{torneio['id']}/inscricao", headers=headers_pessoa)
    assert r.status_code == 400, r.text
    assert "já realizada" in r.json()["detail"]


def test_desinscricao_de_quem_e_jogador_e_juiz_faz_downgrade_sem_deletar(client: TestClient, session: Session):
    """Downgrade, vice-versa: um jogador JOGADOR_E_JUIZ que cancela a
    própria inscrição não perde o vínculo inteiro — só o papel de Jogador;
    o de Juiz continua (downgrade pra tipo=JUIZ, sem DELETE)."""
    loja, token_loja = _criar_loja_autenticada(client, "Loja Juiz 10", "loja.juiz10@gmail.com")
    headers_loja = {"Authorization": f"Bearer {token_loja}"}
    regra = _criar_regra(client, headers_loja)
    torneio = _criar_torneio(client, headers_loja, regra["id"])

    pessoa = _criar_jogador_da_loja(session, loja["id"], "Pessoa Downgrade Jogador")
    token_pessoa = _login(client, "pessoa.downgrade.jogador@gmail.com", "senha123")
    headers_pessoa = {"Authorization": f"Bearer {token_pessoa}"}

    client.post(
        f"/api/lojas/torneios/{torneio['id']}/juizes",
        json={"jogador_criado_id": pessoa["jogador_criado_id"]},
        headers=headers_loja,
    )
    client.post(f"/api/lojas/torneios/{torneio['id']}/inscricao", headers=headers_pessoa)

    link_antes = session.exec(
        select(JogadorTorneioLink).where(
            (JogadorTorneioLink.torneio_id == torneio["id"]) &
            (JogadorTorneioLink.jogador_criado_id == pessoa["jogador_criado_id"])
        )
    ).one()
    assert link_antes.tipo == "JOGADOR_E_JUIZ"

    r = client.delete(f"/api/lojas/torneios/{torneio['id']}/inscricao", headers=headers_pessoa)
    assert r.status_code == 204, r.text

    session.expire_all()
    link_depois = session.get(JogadorTorneioLink, link_antes.id)
    assert link_depois is not None
    assert link_depois.tipo == "JUIZ"


def test_jogador_e_juiz_entra_no_pareamento_e_no_ranking_do_torneio(client: TestClient, session: Session):
    """JOGADOR_E_JUIZ é jogador de verdade também — precisa continuar
    entrando no pareamento de rodadas e no ranking/pódio deste torneio,
    diferente de quem é só Juiz (ver RodadaService.nova_rodada e
    TorneioService.get_torneio_top)."""
    loja, token = _criar_loja_autenticada(client, "Loja Juiz Pareamento", "loja.juizpareamento@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])

    um = _criar_jogador_da_loja(session, loja["id"], "Um Duplo Papel")
    dois = _criar_jogador_da_loja(session, loja["id"], "Dois Comum")
    session.add(JogadorTorneioLink(
        torneio_id=torneio["id"], loja_id=torneio["loja"]["id"], jogador_criado_id=um["jogador_criado_id"],
        apelido=um["nome"], tipo="JOGADOR", pontuacao=0, pontuacao_com_regras=0,
    ))
    session.add(JogadorTorneioLink(
        torneio_id=torneio["id"], loja_id=torneio["loja"]["id"], jogador_criado_id=dois["jogador_criado_id"],
        apelido=dois["nome"], tipo="JOGADOR", pontuacao=0, pontuacao_com_regras=0,
    ))
    session.commit()

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/juizes",
        json={"jogador_criado_id": um["jogador_criado_id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["tipo"] == "JOGADOR_E_JUIZ"

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    pareamento = r.json()
    rodada_id = int(list(pareamento.keys())[0])
    mesa = list(pareamento.values())[0][0]
    ids_na_mesa = {mesa["jogador1"]["jogador_id"], (mesa.get("jogador2") or {}).get("jogador_id")}
    assert um["jogador_id"] in ids_na_mesa

    link_um_id = session.exec(
        select(JogadorTorneioLink).where(
            (JogadorTorneioLink.torneio_id == torneio["id"]) &
            (JogadorTorneioLink.jogador_criado_id == um["jogador_criado_id"])
        )
    ).one().id

    r = client.put(
        "/api/lojas/torneios/rodadas/finalizar",
        json=[{"id_rodada": rodada_id, "id_vencedor": link_um_id}],
        headers=headers,
    )
    assert r.status_code == 200, r.text
    nomes_no_ranking = {item["jogador_nome"] for item in r.json()["ranking"]}
    assert um["nome"] in nomes_no_ranking
