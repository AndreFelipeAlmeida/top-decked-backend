"""Testes funcionais do suporte a Pokémon GO e da composição por partida:
GO segue o mesmo esquema de VGC (catálogo populado, time completo de 6
Pokémon, sem representação de deck), mas com uma peculiaridade — o jogador
escolhe só 3 dos 6 Pokémon do time pra jogar em CADA partida, um recorte que
pode mudar de rodada pra rodada sem nunca alterar o time completo levado ao
torneio. Isso é modelado por ComposicaoPartida/RodadaComposicao
(app/models.py) + garantir_composicao_partida (ComposicaoService.py): pra
TCG/VGC a mesma ComposicaoPartida.id é reaproveitada em toda rodada nova da
participação, só pra GO uma ComposicaoPartida nova (clonada do time) é criada
a cada rodada. Ver docs/COMPOSICAO.md e docs/DIVIDA_TECNICA.md."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.db import get_session
from sqlmodel import Session, select

from app.models import (
    Loja,
    ComposicaoPartida,
    ComposicaoPartidaUnidade,
    Jogador,
    JogadorCriado,
    JogadorTorneioLink,
    RodadaComposicao,
    Torneio,
    UnidadeCatalogo,
    Usuario,
)
from app.services.PokemonCatalogoService import atualizar_catalogo_pokemon
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


def _criar_regra(client: TestClient, headers: dict, tcg: str, nome: str) -> dict:
    payload = {
        "nome": nome,
        "pt_vitoria": 3,
        "pt_derrota": 0,
        "pt_empate": 1,
        "pt_oponente_ganha": 2,
        "pt_oponente_perde": -1,
        "pt_oponente_empate": 0,
        "tcg": tcg,
    }
    r = client.post("/api/lojas/tipoJogador/", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _criar_torneio(client: TestClient, headers: dict, regra_id: int, jogo: str) -> dict:
    payload = {
        "data_planejada": "2026-08-01",
        "jogo": jogo,
        "formato": "PADRAO",
        "vagas": 8,
        "regra_basica_id": regra_id,
    }
    r = client.post("/api/lojas/torneios/criar", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


_contador_external_id = iter(range(1, 1_000_000))


def _seed_catalogo(session: Session, tcg: TCG, quantidade: int, prefixo: str) -> list[int]:
    """Cria unidades de catálogo diretamente (bypassa a PokeAPI de verdade —
    usado nos testes que não são sobre o fetch do catálogo em si, só
    precisam de algumas unidades existentes pra montar um time). external_id
    vem de um contador global do módulo — UnidadeCatalogo tem unique
    constraint em (tcg, external_id), e vários testes semeiam mais de um
    time no mesmo tcg (ex.: um time por jogador)."""
    ids = []
    for i in range(quantidade):
        unidade = UnidadeCatalogo(
            tcg=tcg, external_id=next(_contador_external_id), nome=f"{prefixo}-{i}", manual=True
        )
        session.add(unidade)
        session.commit()
        session.refresh(unidade)
        ids.append(unidade.id)
    return ids


def _adicionar_participante(session: Session, torneio_id: str, regra_id: int, nome: str) -> dict:
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

    # Sem regra extra por padrão — ver comentário equivalente em
    # test_routes_torneio.py._adicionar_participantes.
    torneio = session.get(Torneio, torneio_id)
    link = JogadorTorneioLink(
        torneio_id=torneio_id, loja_id=torneio.loja_id, jogador_criado_id=jogador_criado.id, apelido=nome,
        pontuacao=0, pontuacao_com_regras=0,
    )
    session.add(link)
    session.commit()
    session.refresh(link)

    return {"jogador_id": j.id, "link_id": link.id, "nome": nome}


def _atribuir_time(client: TestClient, headers: dict, torneio_id: str, link_id: int, unidades_ids: list[int]) -> dict:
    composicao_unidades = [{"unidade_catalogo_id": uid, "quantidade": 1} for uid in unidades_ids]
    r = client.patch(
        f"/api/lojas/torneios/{torneio_id}/jogadores/{link_id}/composicao",
        json={"composicao_representacao_id": None, "composicao_unidades": composicao_unidades},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


_POKEMONS_FALSOS = [
    {"external_id": 1, "nome": "bulbasaur"},
    {"external_id": 2, "nome": "ivysaur"},
    {"external_id": 3, "nome": "venusaur"},
]


def test_atualizar_catalogo_popula_go_junto_com_tcg_e_vgc(session: Session):
    """GO reaproveita o mesmo catálogo de espécies da PokeAPI que TCG/VGC,
    só que numa linha própria (mesmo esquema — ver JOGOS_CATALOGO_POKEMON)."""
    with patch(
        "app.services.PokemonCatalogoService.buscar_pokemons_pokeapi",
        return_value=_POKEMONS_FALSOS,
    ):
        novos_go = atualizar_catalogo_pokemon(session, TCG.POKEMON_GO)

    assert novos_go == len(_POKEMONS_FALSOS)

    unidades_go = session.exec(select(UnidadeCatalogo).where(UnidadeCatalogo.tcg == TCG.POKEMON_GO)).all()
    assert {u.external_id for u in unidades_go} == {1, 2, 3}


def test_criar_representacao_e_rejeitada_para_go(client: TestClient, session: Session):
    """GO não tem deck nem representação de deck — só o time completo."""
    unidades_ids = _seed_catalogo(session, TCG.POKEMON_GO, 2, "pokemon-go")
    _, token = _criar_loja_autenticada(client, "Loja Repr GO", "loja.reprgo@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/lojas/composicoes/representacoes",
        json={"tcg": "POKEMON_GO", "unidade_1_id": unidades_ids[0], "unidade_2_id": unidades_ids[1]},
        headers=headers,
    )
    assert r.status_code == 400
    assert "representação de deck" in r.json()["detail"]


def test_time_go_de_6_pokemons_via_mesma_api_de_composicao(client: TestClient, session: Session):
    """O time completo de GO (6 Pokémon) usa a mesma API/componente de
    composição do TCG/VGC — a peculiaridade de escolher 3 por partida é um
    conceito à parte (ComposicaoPartida), não mexe nesse endpoint."""
    unidades_ids = _seed_catalogo(session, TCG.POKEMON_GO, 6, "pokemon-go")
    _, token = _criar_loja_autenticada(client, "Loja Time GO", "loja.timego@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers, "POKEMON_GO", "Regra GO")
    torneio = _criar_torneio(client, headers, regra["id"], "POKEMON_GO")
    participante = _adicionar_participante(session, torneio["id"], regra["id"], "Treinador GO")

    data = _atribuir_time(client, headers, torneio["id"], participante["link_id"], unidades_ids)
    assert data["composicao_representacao_id"] is None
    assert len(data["composicao_unidades"]) == 6
    assert {u["unidade_catalogo_id"] for u in data["composicao_unidades"]} == set(unidades_ids)


def _preparar_torneio_com_dupla(
    client: TestClient, session: Session, jogo: str, tcg_catalogo: TCG, prefixo: str, sufixo_email: str
) -> dict:
    """Monta um torneio de dois jogadores, cada um com time completo de 6
    unidades atribuído, pronto pra gerar rodadas — usado pelos testes de
    composição por partida (mesmo id em TCG/VGC vs. id novo em GO)."""
    unidades_a = _seed_catalogo(session, tcg_catalogo, 6, f"{prefixo}-a")
    unidades_b = _seed_catalogo(session, tcg_catalogo, 6, f"{prefixo}-b")

    _, token = _criar_loja_autenticada(client, f"Loja {prefixo}", f"loja.{sufixo_email}@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra(client, headers, jogo, f"Regra {prefixo}")
    torneio = _criar_torneio(client, headers, regra["id"], jogo)

    jogador_a = _adicionar_participante(session, torneio["id"], regra["id"], f"{prefixo} Um")
    jogador_b = _adicionar_participante(session, torneio["id"], regra["id"], f"{prefixo} Dois")
    _atribuir_time(client, headers, torneio["id"], jogador_a["link_id"], unidades_a)
    _atribuir_time(client, headers, torneio["id"], jogador_b["link_id"], unidades_b)

    r = client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    assert r.status_code == 200, r.text

    return {
        "torneio": torneio,
        "headers": headers,
        "jogador_a": jogador_a,
        "jogador_b": jogador_b,
    }


def _gerar_rodada_e_finalizar(client: TestClient, torneio_id: str, headers: dict, vencedor_link_id: int) -> None:
    r = client.post(f"/api/lojas/torneios/{torneio_id}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    pareamento = r.json()

    resultados = []
    for rodada_id, mesas in pareamento.items():
        mesa = mesas[0]
        vencedor = vencedor_link_id if mesa.get("jogador2") else None
        resultados.append({"id_rodada": int(rodada_id), "id_vencedor": vencedor})

    r = client.put("/api/lojas/torneios/rodadas/finalizar", json=resultados, headers=headers)
    assert r.status_code == 200, r.text


def test_composicao_partida_mantem_o_mesmo_id_em_toda_rodada_para_tcg(client: TestClient, session: Session):
    contexto = _preparar_torneio_com_dupla(
        client, session, "POKEMON", TCG.POKEMON, "TCG-CP", "tcgcp"
    )
    torneio_id = contexto["torneio"]["id"]
    headers = contexto["headers"]
    link_a_id = contexto["jogador_a"]["link_id"]

    _gerar_rodada_e_finalizar(client, torneio_id, headers, link_a_id)
    _gerar_rodada_e_finalizar(client, torneio_id, headers, link_a_id)

    composicoes = session.exec(
        select(RodadaComposicao)
        .where(RodadaComposicao.jogador_torneio_link_id == link_a_id)
        .order_by(RodadaComposicao.id)
    ).all()

    # TCG/VGC: a mesma ComposicaoPartida é reaproveitada em toda rodada nova
    # dessa participação — nunca cria outra (ver garantir_composicao_partida).
    assert len(composicoes) == 2
    assert composicoes[0].composicao_partida_id == composicoes[1].composicao_partida_id


def test_composicao_partida_mantem_o_mesmo_id_em_toda_rodada_para_vgc(client: TestClient, session: Session):
    contexto = _preparar_torneio_com_dupla(
        client, session, "POKEMON_VGC", TCG.POKEMON_VGC, "VGC-CP", "vgccp"
    )
    torneio_id = contexto["torneio"]["id"]
    headers = contexto["headers"]
    link_a_id = contexto["jogador_a"]["link_id"]

    _gerar_rodada_e_finalizar(client, torneio_id, headers, link_a_id)
    _gerar_rodada_e_finalizar(client, torneio_id, headers, link_a_id)

    composicoes = session.exec(
        select(RodadaComposicao)
        .where(RodadaComposicao.jogador_torneio_link_id == link_a_id)
        .order_by(RodadaComposicao.id)
    ).all()

    assert len(composicoes) == 2
    assert composicoes[0].composicao_partida_id == composicoes[1].composicao_partida_id


def test_composicao_partida_ganha_id_novo_em_toda_rodada_para_go(client: TestClient, session: Session):
    contexto = _preparar_torneio_com_dupla(
        client, session, "POKEMON_GO", TCG.POKEMON_GO, "GO-CP", "gocp"
    )
    torneio_id = contexto["torneio"]["id"]
    headers = contexto["headers"]
    link_a_id = contexto["jogador_a"]["link_id"]

    _gerar_rodada_e_finalizar(client, torneio_id, headers, link_a_id)
    _gerar_rodada_e_finalizar(client, torneio_id, headers, link_a_id)

    composicoes = session.exec(
        select(RodadaComposicao)
        .where(RodadaComposicao.jogador_torneio_link_id == link_a_id)
        .order_by(RodadaComposicao.id)
    ).all()

    # Só Pokémon GO cria uma ComposicaoPartida nova a cada rodada — é o que
    # permite escolher um recorte diferente de 3 Pokémon por partida.
    assert len(composicoes) == 2
    assert composicoes[0].composicao_partida_id != composicoes[1].composicao_partida_id


def test_editar_composicao_partida_e_rejeitada_para_tcg(client: TestClient, session: Session):
    contexto = _preparar_torneio_com_dupla(
        client, session, "POKEMON", TCG.POKEMON, "TCG-Rej", "tcgrej"
    )
    torneio_id = contexto["torneio"]["id"]
    headers = contexto["headers"]
    link_a_id = contexto["jogador_a"]["link_id"]

    r = client.post(f"/api/lojas/torneios/{torneio_id}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    rodada_id = int(list(r.json().keys())[0])

    r = client.patch(
        f"/api/lojas/torneios/{torneio_id}/rodadas/{rodada_id}/jogadores/{link_a_id}/composicao-partida",
        json={"unidades": []},
        headers=headers,
    )
    assert r.status_code == 400
    assert "mesma composição em toda partida" in r.json()["detail"]


def test_editar_composicao_partida_e_rejeitada_para_vgc(client: TestClient, session: Session):
    contexto = _preparar_torneio_com_dupla(
        client, session, "POKEMON_VGC", TCG.POKEMON_VGC, "VGC-Rej", "vgcrej"
    )
    torneio_id = contexto["torneio"]["id"]
    headers = contexto["headers"]
    link_a_id = contexto["jogador_a"]["link_id"]

    r = client.post(f"/api/lojas/torneios/{torneio_id}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    rodada_id = int(list(r.json().keys())[0])

    r = client.patch(
        f"/api/lojas/torneios/{torneio_id}/rodadas/{rodada_id}/jogadores/{link_a_id}/composicao-partida",
        json={"unidades": []},
        headers=headers,
    )
    assert r.status_code == 400
    assert "mesma composição em toda partida" in r.json()["detail"]


def test_editar_composicao_partida_go_escolhe_3_de_6_sem_afetar_o_time_completo(client: TestClient, session: Session):
    """O núcleo do pedido: escolher 3 dos 6 Pokémon do time pra uma partida
    de GO não pode, de jeito nenhum, alterar o time completo que o jogador
    levou pro torneio (JogadorComposicaoUnidade)."""
    contexto = _preparar_torneio_com_dupla(
        client, session, "POKEMON_GO", TCG.POKEMON_GO, "GO-Edit", "goedit"
    )
    torneio_id = contexto["torneio"]["id"]
    headers = contexto["headers"]
    link_a_id = contexto["jogador_a"]["link_id"]

    r = client.post(f"/api/lojas/torneios/{torneio_id}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    rodada_id = int(list(r.json().keys())[0])

    link_antes = session.get(JogadorTorneioLink, link_a_id)
    time_completo_ids = [u.unidade_catalogo_id for u in link_antes.composicao_unidades]
    assert len(time_completo_ids) == 6
    escolhidas = time_completo_ids[:3]

    r = client.get(
        f"/api/lojas/torneios/{torneio_id}/rodadas/{rodada_id}/jogadores/{link_a_id}/composicao-partida",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    # Antes de editar, a ComposicaoPartida é uma cópia fiel do time completo.
    assert {u["unidade_catalogo_id"] for u in r.json()["unidades"]} == set(time_completo_ids)

    r = client.patch(
        f"/api/lojas/torneios/{torneio_id}/rodadas/{rodada_id}/jogadores/{link_a_id}/composicao-partida",
        json={"unidades": [{"unidade_catalogo_id": uid, "quantidade": 1} for uid in escolhidas]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert {u["unidade_catalogo_id"] for u in r.json()["unidades"]} == set(escolhidas)

    session.refresh(link_antes)
    time_depois_ids = {u.unidade_catalogo_id for u in link_antes.composicao_unidades}
    assert time_depois_ids == set(time_completo_ids)


def test_editar_composicao_partida_go_rejeita_unidade_fora_do_time(client: TestClient, session: Session):
    contexto = _preparar_torneio_com_dupla(
        client, session, "POKEMON_GO", TCG.POKEMON_GO, "GO-Fora", "gofora"
    )
    torneio_id = contexto["torneio"]["id"]
    headers = contexto["headers"]
    link_a_id = contexto["jogador_a"]["link_id"]

    r = client.post(f"/api/lojas/torneios/{torneio_id}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    rodada_id = int(list(r.json().keys())[0])

    unidade_fora = UnidadeCatalogo(tcg=TCG.POKEMON_GO, external_id=999, nome="fora-do-time", manual=True)
    session.add(unidade_fora)
    session.commit()
    session.refresh(unidade_fora)

    r = client.patch(
        f"/api/lojas/torneios/{torneio_id}/rodadas/{rodada_id}/jogadores/{link_a_id}/composicao-partida",
        json={"unidades": [{"unidade_catalogo_id": unidade_fora.id, "quantidade": 1}]},
        headers=headers,
    )
    assert r.status_code == 400
    assert "não faz parte do time levado para o torneio" in r.json()["detail"]


def test_composicao_partida_de_jogador_que_nao_participa_da_rodada_e_rejeitada(client: TestClient, session: Session):
    contexto = _preparar_torneio_com_dupla(
        client, session, "POKEMON_GO", TCG.POKEMON_GO, "GO-ForaRodada", "goforarodada"
    )
    torneio_id = contexto["torneio"]["id"]
    headers = contexto["headers"]

    r = client.post(f"/api/lojas/torneios/{torneio_id}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    rodada_id = int(list(r.json().keys())[0])

    outro = _adicionar_participante(
        session, torneio_id, contexto["torneio"]["regra_basica_id"], "Intruso"
    )
    r = client.get(
        f"/api/lojas/torneios/{torneio_id}/rodadas/{rodada_id}/jogadores/{outro['link_id']}/composicao-partida",
        headers=headers,
    )
    assert r.status_code == 400
    assert "não participa desta rodada" in r.json()["detail"]


def test_deletar_torneio_go_remove_rodadacomposicao_e_composicaopartida(client: TestClient, session: Session):
    """DELETE /lojas/torneios/{id} precisa limpar RodadaComposicao e
    ComposicaoPartida/ComposicaoPartidaUnidade também — essas tabelas não têm
    relacionamento ORM até Torneio pra cascatear automaticamente, e sem
    PRAGMA foreign_keys habilitado no SQLite nenhum ondelete=CASCADE
    declarado nas colunas é aplicado pelo banco. Pokémon GO é o cenário mais
    completo pra exercitar essa limpeza, já que gera uma ComposicaoPartida
    nova a cada rodada."""
    contexto = _preparar_torneio_com_dupla(
        client, session, "POKEMON_GO", TCG.POKEMON_GO, "GO-Deletar", "godeletar"
    )
    torneio_id = contexto["torneio"]["id"]
    headers = contexto["headers"]
    link_a_id = contexto["jogador_a"]["link_id"]

    _gerar_rodada_e_finalizar(client, torneio_id, headers, link_a_id)

    composicoes_partida_ids = [
        c.composicao_partida_id for c in session.exec(
            select(RodadaComposicao).where(RodadaComposicao.jogador_torneio_link_id == link_a_id)
        ).all()
    ]
    assert len(composicoes_partida_ids) > 0

    r = client.delete(f"/api/lojas/torneios/{torneio_id}", headers=headers)
    assert r.status_code == 204, r.text

    assert session.get(Torneio, torneio_id) is None
    assert session.exec(
        select(RodadaComposicao).where(RodadaComposicao.jogador_torneio_link_id == link_a_id)
    ).first() is None
    for composicao_partida_id in composicoes_partida_ids:
        assert session.get(ComposicaoPartida, composicao_partida_id) is None
        assert session.exec(
            select(ComposicaoPartidaUnidade).where(ComposicaoPartidaUnidade.composicao_partida_id == composicao_partida_id)
        ).first() is None
