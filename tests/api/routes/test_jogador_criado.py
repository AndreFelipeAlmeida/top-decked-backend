"""Testes funcionais da entidade JogadorCriado: a âncora de identidade
(game_id + tcg + apelido, com jogador_id opcional) usada por tudo que uma
loja/torneio faz com um jogador que pode ainda não ter conta registrada na
plataforma — cadastro manual pela loja, import de .tdf, reivindicação
retroativa quando um jogador real registra o mesmo Game ID, e a consequência
direta de tudo isso: ranking e créditos precisam mostrar esses jogadores
mesmo sem conta (ver docs/JOGADORES.md)."""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import JogadorCriado, JogadorTorneioLink
from app.utils.Enums import TCG


def _login(client: TestClient, email: str, senha: str) -> str:
    r = client.post("/api/login/token", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _criar_loja_autenticada(client: TestClient, nome: str, email: str, senha: str = "senha123") -> tuple[dict, str]:
    r = client.post(
        "/api/lojas/",
        json={"nome": nome, "endereco": "Rua X, 1", "email": email, "senha": senha},
    )
    assert r.status_code == 200, r.text
    token = _login(client, email, senha)
    return r.json(), token


def _criar_jogador_autenticado(client: TestClient, nome: str, email: str, senha: str = "senha123") -> tuple[dict, str]:
    r = client.post("/api/jogadores/", json={"nome": nome, "email": email, "senha": senha})
    assert r.status_code == 200, r.text
    token = _login(client, email, senha)
    return r.json(), token


def _criar_torneio(client: TestClient, headers: dict, regra_id: int) -> dict:
    payload = {
        "data_planejada": "2026-08-01",
        "jogo": "POKEMON",
        "formato": "PADRAO",
        "vagas": 8,
        "regra_basica_id": regra_id,
    }
    r = client.post("/api/lojas/torneios/criar", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _criar_regra(client: TestClient, headers: dict) -> dict:
    payload = {
        "nome": "Regra Padrão", "pt_vitoria": 3, "pt_derrota": 0, "pt_empate": 1,
        "pt_oponente_ganha": 2, "pt_oponente_perde": -1, "pt_oponente_empate": 0, "tcg": "POKEMON",
    }
    r = client.post("/api/lojas/tipoJogador/", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _tdf(jogador1_userid: str, jogador2_userid: str) -> bytes:
    """.tdf mínimo: dois jogadores, uma rodada com uma partida entre eles
    (jogador1 vence) — o bastante pra exercitar
    ImportacaoService._criar_relacao_jogador_torneio de ponta a ponta."""
    xml = f"""<?xml version="1.0"?>
<tournament>
  <data>
    <id></id>
    <name>Torneio Importado Teste</name>
    <city>Fortaleza</city>
    <state>CE</state>
    <roundtime>30</roundtime>
    <startdate>08/01/2026</startdate>
  </data>
  <players>
    <player userid="{jogador1_userid}">
      <firstname>Jogador</firstname>
      <lastname>Um</lastname>
    </player>
    <player userid="{jogador2_userid}">
      <firstname>Jogador</firstname>
      <lastname>Dois</lastname>
    </player>
  </players>
  <pods>
    <pod>
      <rounds>
        <round number="1">
          <matches>
            <match outcome="1">
              <player1 userid="{jogador1_userid}" />
              <player2 userid="{jogador2_userid}" />
              <tablenumber>1</tablenumber>
              <timestamp>08/01/2026 10:00:00</timestamp>
            </match>
          </matches>
        </round>
      </rounds>
    </pod>
  </pods>
</tournament>"""
    return xml.encode("utf-8")


def _importar(client: TestClient, headers: dict, jogador1_userid: str, jogador2_userid: str) -> dict:
    arquivo = _tdf(jogador1_userid, jogador2_userid)
    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", arquivo, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_loja_creditar_game_id_sem_conta_registrada_e_rejeitado(client: TestClient, session: Session) -> None:
    """Fix de segurança: creditar um game_id que ninguém reivindicou ainda
    permitiria que qualquer pessoa digitasse o game_id de outra pessoa pra
    "reservar" créditos que iriam parar na conta dela quando ela se
    cadastrasse — sem ela ter pedido nada a esta loja. LojaJogadorLink só
    aceita jogador_id de uma conta real (ver docs/JOGADORES.md)."""
    _, token = _criar_loja_autenticada(client, "Loja A", "loja.a@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/creditos/",
        json={"apelido": "Sem Conta", "game_id": {"tcg": "POKEMON", "id": "gid-001"}},
        headers=headers,
    )
    assert r.status_code == 400, r.text
    assert "conta cadastrada" in r.json()["detail"]

    # Nenhum efeito colateral: a tentativa rejeitada não cria JogadorCriado
    # nem LojaJogadorLink nenhum.
    jogador_criado = session.exec(
        select(JogadorCriado).where(JogadorCriado.game_id == "gid-001")
    ).first()
    assert jogador_criado is None


def test_loja_credita_game_id_ja_reivindicado_vincula_pelo_jogador_id(client: TestClient) -> None:
    _, token_loja = _criar_loja_autenticada(client, "Loja B", "loja.b@gmail.com")
    headers_loja = {"Authorization": f"Bearer {token_loja}"}

    jogador, token_jogador = _criar_jogador_autenticado(client, "Real", "real@gmail.com")
    headers_jogador = {"Authorization": f"Bearer {token_jogador}"}

    # O jogador real primeiro cadastra o próprio Game ID no perfil.
    r = client.put(
        "/api/jogadores/",
        json={"tcgs": [{"tcg": "POKEMON", "id": "gid-002"}]},
        headers=headers_jogador,
    )
    assert r.status_code == 200, r.text

    # A loja credita por esse game_id — como já pertence a uma conta real, o
    # vínculo é criado direto por jogador_id.
    r = client.post(
        "/api/creditos/",
        json={"apelido": "Duplicata", "game_id": {"tcg": "POKEMON", "id": "gid-002"}},
        headers=headers_loja,
    )
    assert r.status_code == 200, r.text
    assert r.json()["jogador_id"] == jogador["id"]


def test_import_cria_jogador_criado_para_participante_sem_conta_e_aparece_no_ranking(
    client: TestClient, session: Session
) -> None:
    _, token = _criar_loja_autenticada(client, "Loja C", "loja.c@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])

    _importar(client, headers, "gid-imp-1", "gid-imp-2")

    jogador_criado_1 = session.exec(select(JogadorCriado).where(JogadorCriado.game_id == "gid-imp-1")).first()
    jogador_criado_2 = session.exec(select(JogadorCriado).where(JogadorCriado.game_id == "gid-imp-2")).first()
    assert jogador_criado_1 is not None and jogador_criado_1.jogador_id is None
    assert jogador_criado_2 is not None and jogador_criado_2.jogador_id is None

    # calcula_ranking_geral ignora participações com 0 pontos (comportamento
    # preexistente, não relacionado a esta mudança) — como o import não
    # aplica nenhuma regra de pontuação sozinho, simula pontuação real aqui
    # (o que uma regra de pontuação normalmente preencheria).
    for link in session.exec(select(JogadorTorneioLink)).all():
        link.pontuacao_com_regras = 3
        session.add(link)
    session.commit()

    # Participante sem conta real: antes desta mudança, ranking geral ignorava
    # completamente essas participações (só iterava Jogador). Agora deve
    # aparecer, identificado pelo apelido do JogadorCriado.
    r = client.get("/api/ranking/geral")
    assert r.status_code == 200, r.text
    nomes = {item["nome_jogador"] for item in r.json()}
    assert "Jogador Um" in nomes
    assert "Jogador Dois" in nomes


def test_jogador_real_reivindica_game_id_ganha_torneio_retroativo_mas_credito_so_apos_reivindicar(
    client: TestClient, session: Session
) -> None:
    """Torneio importado antes de existir conta continua sendo herdado
    retroativamente ao reivindicar o Game ID (não mudou nesta feature — só
    JogadorTorneioLink usa JogadorCriado, sem relação com créditos). Créditos,
    por outro lado, não têm mais esse caminho retroativo: só podem ser
    registrados DEPOIS que uma conta real reivindica o game_id."""
    _, token_loja = _criar_loja_autenticada(client, "Loja D", "loja.d@gmail.com")
    headers_loja = {"Authorization": f"Bearer {token_loja}"}
    regra = _criar_regra(client, headers_loja)
    torneio = _criar_torneio(client, headers_loja, regra["id"])
    _importar(client, headers_loja, "gid-claim-1", "gid-claim-2")

    # Tentar creditar ANTES de existir conta reivindicada é rejeitado.
    r = client.post(
        "/api/creditos/",
        json={"apelido": "A Reivindicar", "game_id": {"tcg": "POKEMON", "id": "gid-claim-1"}},
        headers=headers_loja,
    )
    assert r.status_code == 400, r.text

    jogador, token_jogador = _criar_jogador_autenticado(client, "Dono do ID", "dono@gmail.com")
    headers_jogador = {"Authorization": f"Bearer {token_jogador}"}

    r = client.put(
        "/api/jogadores/",
        json={"tcgs": [{"tcg": "POKEMON", "id": "gid-claim-1"}]},
        headers=headers_jogador,
    )
    assert r.status_code == 200, r.text

    jogador_criado = session.exec(select(JogadorCriado).where(JogadorCriado.game_id == "gid-claim-1")).first()
    assert jogador_criado.jogador_id == jogador["id"]

    # Torneio importado antes de o jogador existir passa a contar (comportamento preexistente, sem mudança).
    r = client.get("/api/jogadores/estatisticas", headers=headers_jogador)
    assert r.status_code == 200, r.text
    assert r.json()["torneio_totais"] == 1

    # Créditos passam a funcionar normalmente DEPOIS da reivindicação.
    r = client.post(
        "/api/creditos/",
        json={"apelido": "Agora Sim", "game_id": {"tcg": "POKEMON", "id": "gid-claim-1"}},
        headers=headers_loja,
    )
    assert r.status_code == 200, r.text
    assert r.json()["jogador_id"] == jogador["id"]

    r = client.get("/api/creditos/jogador", headers=headers_jogador)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["apelido"] == "Agora Sim"


def test_trocar_game_id_nao_afeta_creditos(client: TestClient, session: Session) -> None:
    """Antes, o crédito ficava preso ao JogadorCriado (âncora por game_id) e
    "sumia" da visão do jogador ao trocar de ID — comportamento confuso e, com
    a modelagem antiga, também explorável (ver
    test_loja_creditar_game_id_sem_conta_registrada_e_rejeitado). Agora que
    LojaJogadorLink aponta direto pra jogador_id, o crédito é permanente da
    conta e nunca é afetado por trocar de Game ID (só o histórico de torneio
    importado, que usa JogadorCriado, continua sujeito a isso)."""
    _, token_loja = _criar_loja_autenticada(client, "Loja E", "loja.e@gmail.com")
    headers_loja = {"Authorization": f"Bearer {token_loja}"}

    jogador, token_jogador = _criar_jogador_autenticado(client, "Trocador", "trocador@gmail.com")
    headers_jogador = {"Authorization": f"Bearer {token_jogador}"}

    client.put(
        "/api/jogadores/",
        json={"tcgs": [{"tcg": "POKEMON", "id": "gid-antigo"}]},
        headers=headers_jogador,
    ).raise_for_status()

    r = client.post(
        "/api/creditos/",
        json={"apelido": "Crédito Antigo", "game_id": {"tcg": "POKEMON", "id": "gid-antigo"}},
        headers=headers_loja,
    )
    assert r.status_code == 200, r.text

    # Troca de ID.
    r = client.put(
        "/api/jogadores/",
        json={"tcgs": [{"tcg": "POKEMON", "id": "gid-novo"}]},
        headers=headers_jogador,
    )
    assert r.status_code == 200, r.text

    antigo = session.exec(select(JogadorCriado).where(JogadorCriado.game_id == "gid-antigo")).first()
    novo = session.exec(select(JogadorCriado).where(JogadorCriado.game_id == "gid-novo")).first()
    assert antigo.jogador_id is None
    assert novo.jogador_id == jogador["id"]

    # O crédito continua vinculado à conta normalmente.
    r = client.get("/api/creditos/jogador", headers=headers_jogador)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["apelido"] == "Crédito Antigo"


def test_reivindicar_game_id_de_outra_conta_e_rejeitado(client: TestClient) -> None:
    _dono, token_dono = _criar_jogador_autenticado(client, "Dono", "dono2@gmail.com")
    client.put(
        "/api/jogadores/",
        json={"tcgs": [{"tcg": "POKEMON", "id": "gid-exclusivo"}]},
        headers={"Authorization": f"Bearer {token_dono}"},
    ).raise_for_status()

    _invasor, token_invasor = _criar_jogador_autenticado(client, "Invasor", "invasor@gmail.com")
    r = client.put(
        "/api/jogadores/",
        json={"tcgs": [{"tcg": "POKEMON", "id": "gid-exclusivo"}]},
        headers={"Authorization": f"Bearer {token_invasor}"},
    )
    assert r.status_code == 400
    assert "outra conta" in r.json()["detail"]


def test_impacto_troca_game_id_reflete_torneios_importados(client: TestClient) -> None:
    """creditos_lojas foi removido do impacto: como LojaJogadorLink agora
    aponta direto pra jogador_id (não pro game_id/JogadorCriado), trocar de
    Game ID nunca afeta créditos — só faz sentido avisar sobre o que de fato
    muda, os torneios importados (ver test_trocar_game_id_nao_afeta_creditos)."""
    _, token_loja = _criar_loja_autenticada(client, "Loja F", "loja.f@gmail.com")
    headers_loja = {"Authorization": f"Bearer {token_loja}"}
    regra = _criar_regra(client, headers_loja)
    torneio = _criar_torneio(client, headers_loja, regra["id"])

    jogador, token_jogador = _criar_jogador_autenticado(client, "Impactado", "impactado@gmail.com")
    headers_jogador = {"Authorization": f"Bearer {token_jogador}"}

    client.put(
        "/api/jogadores/",
        json={"tcgs": [{"tcg": "POKEMON", "id": "gid-impacto"}]},
        headers=headers_jogador,
    ).raise_for_status()

    _importar(client, headers_loja, "gid-impacto", "gid-outro")

    r = client.get(
        "/api/jogadores/impacto-troca-gameid",
        params={"tcg": "POKEMON"},
        headers=headers_jogador,
    )
    assert r.status_code == 200, r.text
    dados = r.json()
    assert dados["game_id_atual"] == "gid-impacto"
    assert dados["torneios_importados"] == 1
    assert "creditos_lojas" not in dados


def test_vinculo_direto_a_jogador_existente_continua_funcionando(client: TestClient) -> None:
    """Regressão: create_credito_by_id (loja escolhe um Jogador já cadastrado,
    sem contexto de game_id/TCG) não deve ser afetado pela introdução de
    JogadorCriado — continua usando LojaJogadorLink.jogador_id diretamente."""
    _, token_loja = _criar_loja_autenticada(client, "Loja G", "loja.g@gmail.com")
    headers_loja = {"Authorization": f"Bearer {token_loja}"}

    jogador, _ = _criar_jogador_autenticado(client, "Vínculo Direto", "direto@gmail.com")

    r = client.post(
        f"/api/creditos/{jogador['id']}",
        params={"apelido": "Direto"},
        headers=headers_loja,
    )
    assert r.status_code == 200, r.text
    assert r.json()["jogador_id"] == jogador["id"]
