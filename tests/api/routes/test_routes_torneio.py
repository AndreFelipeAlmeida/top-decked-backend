"""Testes funcionais do fluxo de torneio: criação, pareamento de rodadas
(incluindo bye) e cálculo de pontuação — a área com mais bugs históricos do
sistema (ver docs/DIVIDA_TECNICA.md itens 28-31, 45-47). Servem como suíte de
regressão para exatamente essa classe de bug: qualquer um deles só é
detectável testando através da camada HTTP real (TestClient), não chamando
funções de serviço isoladamente com objetos montados à mão — foi assim que
três bugs críticos passaram despercebidos apesar de validações manuais
anteriores: `nova_rodada` confundindo Jogador.id com JogadorTorneioLink.id,
`rodada.vencedor = <int>` quebrando com 500 em vez de setar `vencedor_id`, e
`editar_torneio_regras` zerando a `regra_extra_id` de todo mundo sempre que
`iniciar_torneio` é chamado sem re-passar a regra básica já configurada."""

from fastapi.testclient import TestClient

from app.core.db import get_session
from sqlmodel import Session, select

from app.models import (
    Loja,
    Jogador,
    JogadorComposicaoUnidade,
    JogadorCriado,
    JogadorTorneioLink,
    PontuacaoExtra,
    RepresentacaoComposicao,
    RepresentacaoComposicaoUnidade,
    Rodada,
    Torneio,
    UnidadeCatalogo,
    Usuario,
)
from app.utils.datetimeUtil import data_agora_brasil
from app.utils.Enums import TCG, StatusAprovacaoLoja


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
        "pt_oponente_ganha": 2,
        "pt_oponente_perde": -1,
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


def _semear_jogadores_ruido(session: Session, quantidade: int) -> None:
    """Cria jogadores soltos (sem torneio/link) só pra empurrar o espaço de
    ids de `Jogador` à frente do espaço de ids de `JogadorTorneioLink` —
    reproduz o cenário real (muito mais jogadores cadastrados no sistema do
    que participações em UM torneio específico) onde o bug de nova_rodada
    (usava Jogador.id em vez de JogadorTorneioLink.id) só se manifestava."""
    for i in range(quantidade):
        u = Usuario(email=f"ruido{i}@gmail.com", tipo="jogador", is_active=True,
                    data_cadastro=data_agora_brasil())
        u.set_senha("senha123")
        session.add(u)
        session.commit()
        session.refresh(u)
        session.add(Jogador(nome=f"Ruido {i}", usuario_id=u.id))
    session.commit()


def _adicionar_participantes(session: Session, torneio_id: str, regra_id: int, nomes: list[str]) -> list[dict]:
    """Insere jogadores + JogadorTorneioLink diretamente no banco pra um
    torneio — bypassa o fluxo de inscrição/GameID (não é o que estes testes
    verificam) e foca no pareamento/pontuação. Retorna, por participante,
    tanto o Jogador.id quanto o JogadorTorneioLink.id — os dois espaços de id
    são usados de propósito em pontos diferentes da API (ver módulo docstring)."""
    participantes = []
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

        jogador_criado = JogadorCriado(
            game_id=f"gid-{nome.lower().replace(' ', '-')}", tcg=TCG.POKEMON, jogador_id=j.id,
        )
        session.add(jogador_criado)
        session.commit()
        session.refresh(jogador_criado)

        # Sem regra extra por padrão (regra_id só serve pra criar o torneio
        # com essa regra básica) — regra extra é sempre um ajuste OPCIONAL
        # por cima da regra básica, não um valor padrão (ver TorneioService).
        link = JogadorTorneioLink(
            torneio_id=torneio_id, jogador_criado_id=jogador_criado.id, apelido=nome,
            pontuacao=0, pontuacao_com_regras=0,
        )
        session.add(link)
        session.commit()
        session.refresh(link)

        participantes.append({"jogador_id": j.id, "link_id": link.id, "nome": nome})

    return participantes


def test_criar_torneio_com_regra_basica(client: TestClient):
    _, token = _criar_loja_autenticada(client, "Loja Torneio", "loja.torneio1@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)

    torneio = _criar_torneio(client, headers, regra["id"])
    assert torneio["jogo"] == "POKEMON"
    assert torneio["formato"] == "PADRAO"
    assert torneio["status"] == "ABERTO"
    assert torneio["regra_basica_id"] == regra["id"]


def test_criar_torneio_com_formato_invalido_e_rejeitado(client: TestClient):
    _, token = _criar_loja_autenticada(client, "Loja Formato Invalido", "loja.formato@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)

    # "Standard" era um formato válido quando o select do frontend ainda
    # oferecia formatos de Magic — hoje o enum FormatoTorneio só aceita
    # PADRAO/GLC/DRAFT (ver docs/DIVIDA_TECNICA.md item 43).
    r = client.post(
        "/api/lojas/torneios/criar",
        json={"data_planejada": "2026-08-01", "jogo": "POKEMON", "formato": "Standard", "vagas": 8},
        headers=headers,
    )
    assert r.status_code == 422


def test_finalizar_torneio_preenche_data_real_quando_ausente(client: TestClient):
    """Um torneio finalizado nunca pode ficar sem inicio_real/fim_real —
    são a base de toda validação de regra de negócio dali pra frente
    (temporada, período de evento, ranking mensal). Quem finaliza sem tê-los
    preenchido manualmente antes (ex.: torneio criado na plataforma, não
    importado) ganha o timestamp de "agora" como aproximação."""
    _, token = _criar_loja_autenticada(client, "Loja Finalizar Data Real", "loja.finalizardatareal@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    assert torneio["inicio_real"] is None
    assert torneio["fim_real"] is None

    r = client.put(f"/api/lojas/torneios/{torneio['id']}/finalizar", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["inicio_real"] is not None
    assert r.json()["fim_real"] is not None


def test_finalizar_torneio_preserva_data_real_ja_preenchida(client: TestClient):
    _, token = _criar_loja_autenticada(client, "Loja Finalizar Data Preenchida", "loja.finalizardatapreenchida@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])

    r = client.put(
        f"/api/lojas/torneios/{torneio['id']}",
        json={"inicio_real": "2026-08-01T10:00:00", "fim_real": "2026-08-01T15:00:00"},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    r = client.put(f"/api/lojas/torneios/{torneio['id']}/finalizar", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["inicio_real"].startswith("2026-08-01T10:00:00")
    assert r.json()["fim_real"].startswith("2026-08-01T15:00:00")


def test_pareamento_com_numero_impar_gera_bye_e_pontua_corretamente(client: TestClient, session: Session):
    _semear_jogadores_ruido(session, 5)

    _, token = _criar_loja_autenticada(client, "Loja Bye", "loja.bye@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])

    participantes = _adicionar_participantes(
        session, torneio["id"], regra["id"], ["Jogador A", "Jogador B", "Jogador C"]
    )

    r = client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "EM_ANDAMENTO"

    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    pareamento = r.json()

    # 3 jogadores => 2 mesas: 1 confronto normal + 1 bye.
    assert len(pareamento) == 2
    mesas_normais = [(rid, dados[0]) for rid, dados in pareamento.items() if dados[0]["jogador2"]]
    mesas_bye = [(rid, dados[0]) for rid, dados in pareamento.items() if not dados[0]["jogador2"]]
    assert len(mesas_normais) == 1
    assert len(mesas_bye) == 1

    jogador_id_para_link_id = {p["jogador_id"]: p["link_id"] for p in participantes}

    rodada_id_normal, mesa_normal = mesas_normais[0]
    vencedor_link_id = jogador_id_para_link_id[mesa_normal["jogador1"]["jogador_id"]]
    perdedor_link_id = jogador_id_para_link_id[mesa_normal["jogador2"]["jogador_id"]]

    rodada_id_bye, mesa_bye = mesas_bye[0]
    bye_link_id = jogador_id_para_link_id[mesa_bye["jogador1"]["jogador_id"]]

    r = client.put(
        "/api/lojas/torneios/rodadas/finalizar",
        json=[
            {"id_rodada": int(rodada_id_normal), "id_vencedor": vencedor_link_id},
            {"id_rodada": int(rodada_id_bye), "id_vencedor": bye_link_id},
        ],
        headers=headers,
    )
    assert r.status_code == 200, r.text

    vencedor = session.get(JogadorTorneioLink, vencedor_link_id)
    perdedor = session.get(JogadorTorneioLink, perdedor_link_id)
    bye_jogador = session.get(JogadorTorneioLink, bye_link_id)

    # Nenhum participante tem regra extra — pontuacao_com_regras é só a
    # regra básica (pt_oponente_ganha/perde só entram se alguém tiver uma
    # regra extra, ver test_regra_extra_soma_delta_proprio_e_bonus_de_oponente).
    assert vencedor.pontuacao_com_regras == 3  # pt_vitoria
    assert perdedor.pontuacao_com_regras == 0  # pt_derrota
    # bye: só pt_vitoria(3), sem bônus de oponente (não existe oponente real)
    assert bye_jogador.pontuacao_com_regras == 3


def test_regra_extra_soma_delta_proprio_e_bonus_de_oponente(client: TestClient, session: Session):
    """Regra extra (JogadorTorneioLink.regra_extra_id) nunca substitui a
    regra básica do torneio — só soma/subtrai por cima dela. Um jogador com
    regra extra ganha o próprio delta de vitória/derrota/empate dela, E o
    OPONENTE dele ganha o delta de oponente_ganha/oponente_perde/oponente_empate
    dessa mesma regra extra (ver TorneioService.calcular_pontuacao_rodada).
    Também confirma que limpar a regra extra (None, via PATCH .../regra) volta
    o jogador a pontuar só pela regra básica, sem cair de volta pra ela como
    "regra própria" (comportamento do modelo antigo, já removido)."""
    _, token = _criar_loja_autenticada(client, "Loja Regra Extra", "loja.regraextra@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra_basica = _criar_regra(
        client, headers, nome="Básica", pt_vitoria=3, pt_derrota=0, pt_empate=1,
        pt_oponente_ganha=0, pt_oponente_perde=0, pt_oponente_empate=0,
    )
    torneio = _criar_torneio(client, headers, regra_basica["id"])
    participantes = _adicionar_participantes(session, torneio["id"], regra_basica["id"], ["Vencedor", "Perdedor"])
    link_por_nome = {p["nome"]: p["link_id"] for p in participantes}

    regra_extra_vencedor = _criar_regra(
        client, headers, nome="Extra Vencedor", pt_vitoria=10, pt_derrota=0, pt_empate=0,
        pt_oponente_ganha=0, pt_oponente_perde=100, pt_oponente_empate=0,
    )
    regra_extra_perdedor = _criar_regra(
        client, headers, nome="Extra Perdedor", pt_vitoria=0, pt_derrota=-5, pt_empate=0,
        pt_oponente_ganha=50, pt_oponente_perde=0, pt_oponente_empate=0,
    )

    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/jogadores/{link_por_nome['Vencedor']}/regra",
        json={"regra_extra_id": regra_extra_vencedor["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/jogadores/{link_por_nome['Perdedor']}/regra",
        json={"regra_extra_id": regra_extra_perdedor["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    rodada_id = int(list(r.json().keys())[0])

    r = client.put(
        "/api/lojas/torneios/rodadas/finalizar",
        json=[{"id_rodada": rodada_id, "id_vencedor": link_por_nome["Vencedor"]}],
        headers=headers,
    )
    assert r.status_code == 200, r.text

    vencedor_link = session.get(JogadorTorneioLink, link_por_nome["Vencedor"])
    perdedor_link = session.get(JogadorTorneioLink, link_por_nome["Perdedor"])
    # vencedor: base.pt_vitoria(3) + própria extra.pt_vitoria(10) + extra do perdedor.pt_oponente_ganha(50)
    assert vencedor_link.pontuacao_com_regras == 63
    # perdedor: base.pt_derrota(0) + própria extra.pt_derrota(-5) + extra do vencedor.pt_oponente_perde(100)
    assert perdedor_link.pontuacao_com_regras == 95

    # Remove a regra extra do vencedor — ele passa a pontuar só pela básica,
    # o perdedor continua recebendo o bônus da SUA própria regra extra.
    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/jogadores/{link_por_nome['Vencedor']}/regra",
        json={"regra_extra_id": None},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    session.refresh(vencedor_link)
    session.refresh(perdedor_link)
    assert vencedor_link.pontuacao_com_regras == 53  # 3 (base) + 0 (sem extra) + 50 (extra do perdedor)
    assert perdedor_link.pontuacao_com_regras == -5  # 0 (base) + -5 (própria extra) + 0 (vencedor sem extra)


def test_atualizar_regra_extra_de_jogador_de_outra_loja_e_rejeitada(client: TestClient, session: Session):
    _, token_dono = _criar_loja_autenticada(client, "Loja Dona Regra", "loja.dona.regraextra@gmail.com")
    headers_dono = {"Authorization": f"Bearer {token_dono}"}
    regra = _criar_regra(client, headers_dono)
    torneio = _criar_torneio(client, headers_dono, regra["id"])
    participante = _adicionar_participantes(session, torneio["id"], regra["id"], ["Alvo"])[0]

    _, token_intruso = _criar_loja_autenticada(client, "Loja Intrusa Regra", "loja.intrusa.regraextra@gmail.com")
    headers_intruso = {"Authorization": f"Bearer {token_intruso}"}
    regra_intrusa = _criar_regra(client, headers_intruso, nome="Regra Intrusa")

    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/jogadores/{participante['link_id']}/regra",
        json={"regra_extra_id": regra_intrusa["id"]},
        headers=headers_dono,
    )
    assert r.status_code == 404


def test_finalizar_rodada_com_vencedor_invalido_e_rejeitado(client: TestClient, session: Session):
    _, token = _criar_loja_autenticada(client, "Loja Rejeita", "loja.rejeita@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    participantes = _adicionar_participantes(session, torneio["id"], regra["id"], ["X", "Y"])

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    rodada_id = int(list(r.json().keys())[0])

    # id_vencedor que não participa desta rodada.
    r = client.put(
        "/api/lojas/torneios/rodadas/finalizar",
        json=[{"id_rodada": rodada_id, "id_vencedor": 999999}],
        headers=headers,
    )
    assert r.status_code == 400


def test_recalcular_pontuacao_reaplica_regra_do_zero(client: TestClient, session: Session):
    _, token = _criar_loja_autenticada(client, "Loja Recalcular", "loja.recalc@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    participantes = _adicionar_participantes(session, torneio["id"], regra["id"], ["Um", "Dois"])

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    pareamento = r.json()
    rodada_id = int(list(pareamento.keys())[0])
    jogador_id_para_link_id = {p["jogador_id"]: p["link_id"] for p in participantes}
    mesa = list(pareamento.values())[0][0]
    vencedor_link_id = jogador_id_para_link_id[mesa["jogador1"]["jogador_id"]]

    client.put(
        "/api/lojas/torneios/rodadas/finalizar",
        json=[{"id_rodada": rodada_id, "id_vencedor": vencedor_link_id}],
        headers=headers,
    )

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/recalcular-pontuacao",
        json={"regra_basica_id": regra["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    jogadores = {j["jogador_id"]: j for j in r.json()["jogadores"]}
    vencedor_jogador_id = [k for k, v in jogador_id_para_link_id.items() if v == vencedor_link_id][0]
    assert jogadores[vencedor_jogador_id]["pontuacao_com_regras"] == 3


def test_recalcular_pontuacao_aceita_pontuacao_de_participacao_ainda_nao_salva(client: TestClient, session: Session):
    """Mesmo padrão da regra básica: o organizador não precisa clicar em
    "Salvar Alterações" antes de recalcular com a pontuação de participação
    que acabou de escolher no formulário — o valor enviado no recalcular já
    vale (e fica salvo pro torneio, igual acontece com regra_basica_id)."""
    _, token = _criar_loja_autenticada(client, "Loja Recalcular PP", "loja.recalcpp@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    _adicionar_participantes(session, torneio["id"], regra["id"], ["Um", "Dois"])

    assert torneio["pontuacao_de_participacao"] == 0

    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/recalcular-pontuacao",
        json={"regra_basica_id": regra["id"], "pontuacao_de_participacao": 10},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["pontuacao_de_participacao"] == 10
    for jogador in r.json()["jogadores"]:
        assert jogador["pontuacao_com_regras"] == 10

    # E fica persistido — não é só um cálculo "de mentira" pra essa resposta.
    r = client.get(f"/api/lojas/torneios/{torneio['id']}", headers=headers)
    assert r.json()["pontuacao_de_participacao"] == 10


def test_torneio_melhor_de_default_e_md1_e_pode_ser_configurado(client: TestClient):
    """Torneios podem ser "melhor de X" (MD1/MD3/MD5 — ver Torneio.melhor_de)
    — informativo apenas, o sistema não modela partidas individuais dentro
    de uma rodada (ver docs/PARTIDAS.md). Default é MD1 quando o campo não é
    enviado."""
    _, token = _criar_loja_autenticada(client, "Loja MD Default", "loja.mddefault@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)

    torneio_default = _criar_torneio(client, headers, regra["id"])
    assert torneio_default["melhor_de"] == "MD1"

    torneio_md3 = _criar_torneio(client, headers, regra["id"], melhor_de="MD3")
    assert torneio_md3["melhor_de"] == "MD3"


def test_get_torneio_retorna_rodadas_com_id_e_vencedor_id(client: TestClient, session: Session):
    """Regressão: retornar_torneio_completo montava o dict das rodadas com a
    chave "vencedor" (o relacionamento) em vez de "vencedor_id" (a coluna
    que RodadaPublico de fato espera) — o vencedor da rodada nunca aparecia
    na resposta da API, sempre None independente do resultado real. Também
    confirma que cada rodada agora expõe seu id."""
    _, token = _criar_loja_autenticada(client, "Loja Rodadas Publico", "loja.rodadaspublico@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    participantes = _adicionar_participantes(session, torneio["id"], regra["id"], ["Um", "Dois"])
    jogador_id_para_link_id = {p["jogador_id"]: p["link_id"] for p in participantes}

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    pareamento = r.json()
    rodada_id = int(list(pareamento.keys())[0])
    mesa = list(pareamento.values())[0][0]
    vencedor_link_id = jogador_id_para_link_id[mesa["jogador1"]["jogador_id"]]

    r = client.put(
        "/api/lojas/torneios/rodadas/finalizar",
        json=[{"id_rodada": rodada_id, "id_vencedor": vencedor_link_id}],
        headers=headers,
    )
    assert r.status_code == 200, r.text

    r = client.get(f"/api/lojas/torneios/{torneio['id']}", headers=headers)
    assert r.status_code == 200, r.text
    rodadas = r.json()["rodadas"]
    assert len(rodadas) == 1
    rodada_publica = rodadas[0]
    assert rodada_publica["id"] == rodada_id
    assert rodada_publica["vencedor_id"] == vencedor_link_id
    assert rodada_publica["finalizada"] is True


def test_editar_rodada_atualiza_vencedor_e_pontuacao_sem_dobrar_ao_reeditar(client: TestClient, session: Session):
    """A aba "Rodadas" do frontend pode chamar PATCH .../rodadas/{id} várias
    vezes enquanto o organizador ajusta o resultado — diferente de PUT
    rodadas/finalizar (que trava depois de uma chamada), aqui a pontuação
    precisa ficar correta mesmo reeditando o mesmo vencedor duas vezes (sem
    dobrar, já que calcular_pontuacao_rodada soma incrementalmente)."""
    _, token = _criar_loja_autenticada(client, "Loja Editar Rodada", "loja.editarrodada@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    participantes = _adicionar_participantes(session, torneio["id"], regra["id"], ["Um", "Dois"])
    jogador_id_para_link_id = {p["jogador_id"]: p["link_id"] for p in participantes}

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    pareamento = r.json()
    rodada_id = int(list(pareamento.keys())[0])
    mesa = list(pareamento.values())[0][0]
    vencedor_link_id = jogador_id_para_link_id[mesa["jogador1"]["jogador_id"]]
    perdedor_link_id = jogador_id_para_link_id[mesa["jogador2"]["jogador_id"]]

    for _ in range(2):
        r = client.patch(
            f"/api/lojas/torneios/{torneio['id']}/rodadas/{rodada_id}",
            json={"vencedor_id": vencedor_link_id},
            headers=headers,
        )
        assert r.status_code == 200, r.text

    vencedor_link = session.get(JogadorTorneioLink, vencedor_link_id)
    perdedor_link = session.get(JogadorTorneioLink, perdedor_link_id)
    assert vencedor_link.pontuacao_com_regras == 3  # pt_vitoria, sem regra extra
    assert perdedor_link.pontuacao_com_regras == 0  # pt_derrota, sem regra extra

    rodada = session.get(Rodada, rodada_id)
    assert rodada.vencedor_id == vencedor_link_id
    assert rodada.finalizada is True


def test_editar_rodada_troca_pareamento_e_reseta_resultado_antigo(client: TestClient, session: Session):
    """Trocar Jogador 1/Jogador 2 de uma mesa já com resultado declarado
    precisa invalidar esse resultado — um vencedor apontando pra um jogador
    que não está mais na mesa seria um dado incoerente."""
    _, token = _criar_loja_autenticada(client, "Loja Troca Pareamento", "loja.trocapareamento@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    participantes = _adicionar_participantes(session, torneio["id"], regra["id"], ["Um", "Dois", "Tres"])
    jogador_id_para_link_id = {p["jogador_id"]: p["link_id"] for p in participantes}
    todos_link_ids = set(jogador_id_para_link_id.values())

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    pareamento = r.json()

    # Com 3 jogadores, uma mesa é um confronto normal e a outra é um bye.
    rodada_normal_id = None
    mesa_normal = None
    for rodada_id_str, mesas in pareamento.items():
        mesa = mesas[0]
        if mesa.get("jogador2"):
            rodada_normal_id = int(rodada_id_str)
            mesa_normal = mesa

    vencedor_link_id = jogador_id_para_link_id[mesa_normal["jogador1"]["jogador_id"]]
    jogador2_atual_link_id = jogador_id_para_link_id[mesa_normal["jogador2"]["jogador_id"]]
    terceiro_link_id = list(todos_link_ids - {vencedor_link_id, jogador2_atual_link_id})[0]

    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/rodadas/{rodada_normal_id}",
        json={"vencedor_id": vencedor_link_id},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # Troca o Jogador 2 da mesa pelo jogador que estava de bye.
    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/rodadas/{rodada_normal_id}",
        json={"jogador2_id": terceiro_link_id},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    rodada = session.get(Rodada, rodada_normal_id)
    assert rodada.jogador2_id == terceiro_link_id
    # O resultado antigo (declarado antes da troca) foi invalidado.
    assert rodada.vencedor_id is None
    assert rodada.finalizada is False


def test_editar_rodada_rejeita_vencedor_fora_da_mesa(client: TestClient, session: Session):
    _, token = _criar_loja_autenticada(client, "Loja Vencedor Invalido", "loja.vencedorinvalidorodada@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    _adicionar_participantes(session, torneio["id"], regra["id"], ["Um", "Dois"])

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    rodada_id = int(list(r.json().keys())[0])

    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/rodadas/{rodada_id}",
        json={"vencedor_id": 999999},
        headers=headers,
    )
    assert r.status_code == 400


def test_editar_rodada_rejeita_jogador1_igual_jogador2(client: TestClient, session: Session):
    _, token = _criar_loja_autenticada(client, "Loja Mesmo Jogador", "loja.mesmojogadorrodada@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    _adicionar_participantes(session, torneio["id"], regra["id"], ["Um", "Dois"])

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    rodada_id = int(list(r.json().keys())[0])
    rodada = session.get(Rodada, rodada_id)

    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/rodadas/{rodada_id}",
        json={"jogador2_id": rodada.jogador1_id},
        headers=headers,
    )
    assert r.status_code == 400


def test_editar_torneio_com_formato_vazio_e_tratado_como_sem_formato(client: TestClient, session: Session):
    """Regressão: o <Select> de "Formato" na tela de editar torneio usa
    `torneio?.formato ?? ''` como valor inicial — um torneio sem formato
    definido (comum em importados) faz o form submeter `formato: ""`, que o
    enum `FormatoTorneio` rejeitava com 422 em vez de tratar como "sem
    formato", impedindo salvar QUALQUER alteração nesse torneio."""
    _, token = _criar_loja_autenticada(client, "Loja Formato Vazio", "loja.formatovazio@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"], formato=None)
    assert torneio["formato"] is None

    r = client.put(
        f"/api/lojas/torneios/{torneio['id']}",
        json={"nome": "Torneio Renomeado", "formato": ""},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "Torneio Renomeado"
    assert r.json()["formato"] is None


def test_atualizar_composicao_pela_segunda_vez_nao_quebra_com_instancia_deletada(client: TestClient, session: Session):
    """Regressão: PATCH .../composicao quebrava com 500
    (`InvalidRequestError: Instance ... has been deleted. Use the
    make_transient() function...`) sempre que o jogador JÁ tinha unidades
    cadastradas (ou seja, a partir da 2ª chamada em diante — ex.: escolher
    uma composição completa e depois só atribuir uma representação).
    Causa: o código apagava as unidades antigas uma a uma com
    `session.delete(unidade)` sem removê-las da coleção
    `link.composicao_unidades` em si — o objeto excluído ficava "preso" nessa
    coleção em memória, e o cascade save-update do `session.add(link)`
    seguinte encontrava um objeto já apagado e estourava. Corrigido trocando
    por `link.composicao_unidades.clear()` (que aciona o cascade
    delete-orphan corretamente e mantém a coleção em sincronia)."""
    _, token = _criar_loja_autenticada(client, "Loja Composicao Dupla", "loja.composicaodupla@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    participante = _adicionar_participantes(session, torneio["id"], regra["id"], ["Alvo"])[0]

    unidades_ids = []
    for i in range(3):
        unidade = UnidadeCatalogo(tcg=TCG.POKEMON, external_id=9000 + i, nome=f"unidade-dupla-{i}", manual=True)
        session.add(unidade)
        session.commit()
        session.refresh(unidade)
        unidades_ids.append(unidade.id)

    representacao = RepresentacaoComposicao(tcg=TCG.POKEMON, nome="Representação Dupla")
    session.add(representacao)
    session.commit()
    session.refresh(representacao)
    session.add(RepresentacaoComposicaoUnidade(representacao_id=representacao.id, ordem=0, unidade_catalogo_id=unidades_ids[0]))
    session.add(RepresentacaoComposicaoUnidade(representacao_id=representacao.id, ordem=1, unidade_catalogo_id=unidades_ids[1]))
    session.commit()

    # 1ª chamada: monta a composição completa (sem unidades cadastradas
    # ainda, esse caminho já funcionava antes da correção).
    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/jogadores/{participante['link_id']}/composicao",
        json={
            "composicao_representacao_id": None,
            "composicao_unidades": [{"unidade_catalogo_id": uid, "quantidade": 1} for uid in unidades_ids],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # 2ª chamada: só atribui uma representação (reenviando as mesmas
    # unidades, como o frontend faz) — é essa chamada que quebrava, porque
    # já existem `JogadorComposicaoUnidade` cadastradas pra apagar/recriar.
    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/jogadores/{participante['link_id']}/composicao",
        json={
            "composicao_representacao_id": representacao.id,
            "composicao_unidades": [{"unidade_catalogo_id": uid, "quantidade": 1} for uid in unidades_ids],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["composicao_representacao_id"] == representacao.id
    assert len(r.json()["composicao_unidades"]) == 3


def test_deletar_torneio_remove_torneio_e_todas_as_dependencias(client: TestClient, session: Session):
    """DELETE /lojas/torneios/{id} precisa apagar o torneio inteiro e tudo
    que depende dele — sem isso sobrariam linhas órfãs (JogadorTorneioLink,
    Rodada, JogadorComposicaoUnidade, PontuacaoExtra), já que o projeto não
    usa migrations nem tem PRAGMA foreign_keys habilitado no SQLite (nenhum
    ondelete=CASCADE declarado nas colunas é de fato aplicado pelo banco)."""
    _, token = _criar_loja_autenticada(client, "Loja Deletar Torneio", "loja.deletartorneio@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers)
    torneio = _criar_torneio(client, headers, regra["id"])
    participantes = _adicionar_participantes(session, torneio["id"], regra["id"], ["Um", "Dois"])

    unidade = UnidadeCatalogo(tcg=TCG.POKEMON, external_id=7777, nome="unidade-pra-deletar", manual=True)
    session.add(unidade)
    session.commit()
    session.refresh(unidade)
    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/jogadores/{participantes[0]['link_id']}/composicao",
        json={"composicao_representacao_id": None,
              "composicao_unidades": [{"unidade_catalogo_id": unidade.id, "quantidade": 1}]},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    rodada_id = int(list(r.json().keys())[0])

    jogador_criado_id = session.get(JogadorTorneioLink, participantes[0]["link_id"]).jogador_criado_id
    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/pontuacao-extra",
        json={
            "jogador_criado_id": jogador_criado_id,
            "motivo": "OUTROS",
            "descricao": "Ajudou na organização",
            "pontos": 2,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    pontuacao_extra_id = r.json()["id"]

    r = client.delete(f"/api/lojas/torneios/{torneio['id']}", headers=headers)
    assert r.status_code == 204, r.text

    assert session.get(Torneio, torneio["id"]) is None
    assert session.get(Rodada, rodada_id) is None
    for participante in participantes:
        assert session.get(JogadorTorneioLink, participante["link_id"]) is None
    assert session.exec(
        select(JogadorComposicaoUnidade).where(JogadorComposicaoUnidade.unidade_catalogo_id == unidade.id)
    ).first() is None
    assert session.get(PontuacaoExtra, pontuacao_extra_id) is None


def test_deletar_torneio_inexistente_e_rejeitado(client: TestClient):
    _, token = _criar_loja_autenticada(client, "Loja Deletar 404", "loja.deletar404@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.delete("/api/lojas/torneios/id-que-nao-existe", headers=headers)
    assert r.status_code == 404


def test_deletar_torneio_de_outra_loja_e_rejeitado(client: TestClient):
    _, token_dono = _criar_loja_autenticada(client, "Loja Dona", "loja.dona.deletar@gmail.com")
    headers_dono = {"Authorization": f"Bearer {token_dono}"}
    regra = _criar_regra(client, headers_dono)
    torneio = _criar_torneio(client, headers_dono, regra["id"])

    _, token_intruso = _criar_loja_autenticada(client, "Loja Intrusa", "loja.intrusa.deletar@gmail.com")
    headers_intruso = {"Authorization": f"Bearer {token_intruso}"}

    r = client.delete(f"/api/lojas/torneios/{torneio['id']}", headers=headers_intruso)
    assert r.status_code == 403
