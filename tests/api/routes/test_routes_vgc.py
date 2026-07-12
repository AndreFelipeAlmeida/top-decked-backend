"""Testes funcionais do suporte a Pokémon VGC: mesmo catálogo/API/componente
de composição do Pokémon TCG, mas sem representação de deck (VGC não tem
"deck" — só o time completo de 6 Pokémon) e com a mesma pontuação/desempate
suíço do TCG. Ver docs/COMPOSICAO.md e docs/DIVIDA_TECNICA.md."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.db import get_session
from sqlmodel import Session, select

from app.models import (
    Loja,
    CatalogoAtualizacao,
    Jogador,
    JogadorCriado,
    JogadorTorneioLink,
    RepresentacaoComposicao,
    RepresentacaoComposicaoUnidade,
    UnidadeCatalogo,
    Usuario,
)
from app.services.PokemonCatalogoService import atualizar_catalogo_pokemon, garantir_catalogo_atualizado
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


def _criar_regra_vgc(client: TestClient, headers: dict) -> dict:
    payload = {
        "nome": "Regra VGC",
        "pt_vitoria": 3,
        "pt_derrota": 0,
        "pt_empate": 1,
        "pt_oponente_ganha": 2,
        "pt_oponente_perde": -1,
        "pt_oponente_empate": 0,
        "tcg": "POKEMON_VGC",
    }
    r = client.post("/api/lojas/tipoJogador/", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _criar_torneio_vgc(client: TestClient, headers: dict, regra_id: int) -> dict:
    payload = {
        "data_planejada": "2026-08-01",
        "jogo": "POKEMON_VGC",
        "formato": "PADRAO",
        "vagas": 8,
        "regra_basica_id": regra_id,
    }
    r = client.post("/api/lojas/torneios/criar", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _seed_catalogo_vgc(session: Session, quantidade: int) -> list[int]:
    """Cria unidades de catálogo VGC diretamente (bypassa a PokeAPI de
    verdade — usado nos testes que não são sobre o fetch do catálogo em si,
    só precisam de algumas unidades existentes pra montar um time)."""
    ids = []
    for i in range(quantidade):
        unidade = UnidadeCatalogo(tcg=TCG.POKEMON_VGC, external_id=100 + i, nome=f"pokemon-vgc-{i}", manual=True)
        session.add(unidade)
        session.commit()
        session.refresh(unidade)
        ids.append(unidade.id)
    return ids


def _adicionar_participante(session: Session, torneio_id: str, regra_id: int, nome: str) -> dict:
    u = Usuario(email=f"{nome.lower()}@gmail.com", tipo="jogador", is_active=True, data_cadastro=data_agora_brasil())
    u.set_senha("senha123")
    session.add(u)
    session.commit()
    session.refresh(u)

    j = Jogador(nome=nome, usuario_id=u.id)
    session.add(j)
    session.commit()
    session.refresh(j)

    jogador_criado = JogadorCriado(game_id=f"gid-{nome.lower()}", tcg=TCG.POKEMON_VGC, jogador_id=j.id)
    session.add(jogador_criado)
    session.commit()
    session.refresh(jogador_criado)

    # Sem regra extra por padrão — ver comentário equivalente em
    # test_routes_torneio.py._adicionar_participantes.
    link = JogadorTorneioLink(
        torneio_id=torneio_id, jogador_criado_id=jogador_criado.id, apelido=nome,
        pontuacao=0, pontuacao_com_regras=0,
    )
    session.add(link)
    session.commit()
    session.refresh(link)

    return {"jogador_id": j.id, "link_id": link.id, "nome": nome}


_POKEMONS_FALSOS = [
    {"external_id": 1, "nome": "bulbasaur"},
    {"external_id": 2, "nome": "ivysaur"},
    {"external_id": 3, "nome": "venusaur"},
]


def test_atualizar_catalogo_popula_pokemon_e_vgc_separadamente(session: Session):
    with patch(
        "app.services.PokemonCatalogoService.buscar_pokemons_pokeapi",
        return_value=_POKEMONS_FALSOS,
    ):
        novos_tcg = atualizar_catalogo_pokemon(session, TCG.POKEMON)
        novos_vgc = atualizar_catalogo_pokemon(session, TCG.POKEMON_VGC)

    assert novos_tcg == len(_POKEMONS_FALSOS)
    assert novos_vgc == len(_POKEMONS_FALSOS)

    unidades_tcg = session.exec(select(UnidadeCatalogo).where(UnidadeCatalogo.tcg == TCG.POKEMON)).all()
    unidades_vgc = session.exec(select(UnidadeCatalogo).where(UnidadeCatalogo.tcg == TCG.POKEMON_VGC)).all()

    # Mesmos external_id/nome nos dois — é o mesmo catálogo de espécies,
    # só com linhas próprias por jogo (ver JOGOS_CATALOGO_POKEMON).
    assert {u.external_id for u in unidades_tcg} == {1, 2, 3}
    assert {u.external_id for u in unidades_vgc} == {1, 2, 3}
    assert unidades_tcg[0].id != unidades_vgc[0].id

    controle_tcg = session.get(CatalogoAtualizacao, TCG.POKEMON)
    controle_vgc = session.get(CatalogoAtualizacao, TCG.POKEMON_VGC)
    assert controle_tcg is not None
    assert controle_vgc is not None


def test_garantir_catalogo_atualizado_popula_ambos_do_zero(session: Session):
    with patch(
        "app.services.PokemonCatalogoService.buscar_pokemons_pokeapi",
        return_value=_POKEMONS_FALSOS,
    ):
        garantir_catalogo_atualizado(session)

    unidades_tcg = session.exec(select(UnidadeCatalogo).where(UnidadeCatalogo.tcg == TCG.POKEMON)).all()
    unidades_vgc = session.exec(select(UnidadeCatalogo).where(UnidadeCatalogo.tcg == TCG.POKEMON_VGC)).all()
    assert len(unidades_tcg) == len(_POKEMONS_FALSOS)
    assert len(unidades_vgc) == len(_POKEMONS_FALSOS)


def test_unidades_endpoint_busca_vgc_reaproveitando_a_mesma_rota(client: TestClient, session: Session):
    _seed_catalogo_vgc(session, 3)
    _, token = _criar_loja_autenticada(client, "Loja Unidades VGC", "loja.unidadesvgc@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/api/unidades", params={"tcg": "POKEMON_VGC", "busca": "pokemon-vgc"}, headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3
    assert all(u["tcg"] == "POKEMON_VGC" for u in r.json())


def test_criar_representacao_e_rejeitada_para_vgc(client: TestClient, session: Session):
    """VGC não tem deck nem representação de deck — só o time completo."""
    unidades_ids = _seed_catalogo_vgc(session, 2)
    _, token = _criar_loja_autenticada(client, "Loja Repr VGC", "loja.reprvgc@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/lojas/composicoes/representacoes",
        json={"tcg": "POKEMON_VGC", "unidade_1_id": unidades_ids[0], "unidade_2_id": unidades_ids[1]},
        headers=headers,
    )
    assert r.status_code == 400
    assert "representação de deck" in r.json()["detail"]


def test_atribuir_representacao_a_torneio_vgc_e_rejeitada(client: TestClient, session: Session):
    """Mesmo que alguém tente forçar um composicao_representacao_id numa
    participação de torneio VGC (via PATCH direto), a rota rejeita — reforça
    a mesma regra do endpoint de criar representação, com mensagem clara."""
    unidades_ids = _seed_catalogo_vgc(session, 2)

    representacao = RepresentacaoComposicao(tcg=TCG.POKEMON_VGC, nome="Forçada")
    session.add(representacao)
    session.commit()
    session.refresh(representacao)
    session.add(RepresentacaoComposicaoUnidade(representacao_id=representacao.id, ordem=0, unidade_catalogo_id=unidades_ids[0]))
    session.add(RepresentacaoComposicaoUnidade(representacao_id=representacao.id, ordem=1, unidade_catalogo_id=unidades_ids[1]))
    session.commit()

    _, token = _criar_loja_autenticada(client, "Loja Forca VGC", "loja.forcavgc@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra_vgc(client, headers)
    torneio = _criar_torneio_vgc(client, headers, regra["id"])
    participante = _adicionar_participante(session, torneio["id"], regra["id"], "Alvo")

    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/jogadores/{participante['link_id']}/composicao",
        json={"composicao_representacao_id": representacao.id, "composicao_unidades": []},
        headers=headers,
    )
    assert r.status_code == 400
    assert "representação de deck" in r.json()["detail"]


def test_time_vgc_de_6_pokemons_via_mesma_api_de_composicao(client: TestClient, session: Session):
    """O pedido original: VGC usa a mesma API/componente de composição do
    TCG — só que só o time completo importa (6 Pokémon), sem representação."""
    unidades_ids = _seed_catalogo_vgc(session, 6)
    _, token = _criar_loja_autenticada(client, "Loja Time VGC", "loja.timevgc@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra_vgc(client, headers)
    torneio = _criar_torneio_vgc(client, headers, regra["id"])
    participante = _adicionar_participante(session, torneio["id"], regra["id"], "Treinador")

    composicao_unidades = [{"unidade_catalogo_id": uid, "quantidade": 1} for uid in unidades_ids]
    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/jogadores/{participante['link_id']}/composicao",
        json={"composicao_representacao_id": None, "composicao_unidades": composicao_unidades},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["composicao_representacao_id"] is None
    assert len(data["composicao_unidades"]) == 6
    assert {u["unidade_catalogo_id"] for u in data["composicao_unidades"]} == set(unidades_ids)


def test_time_vgc_com_unidade_de_outro_jogo_e_rejeitado(client: TestClient, session: Session):
    unidade_tcg = UnidadeCatalogo(tcg=TCG.POKEMON, external_id=999, nome="so-do-tcg", manual=True)
    session.add(unidade_tcg)
    session.commit()
    session.refresh(unidade_tcg)

    _, token = _criar_loja_autenticada(client, "Loja Mix VGC", "loja.mixvgc@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra_vgc(client, headers)
    torneio = _criar_torneio_vgc(client, headers, regra["id"])
    participante = _adicionar_participante(session, torneio["id"], regra["id"], "Confuso")

    r = client.patch(
        f"/api/lojas/torneios/{torneio['id']}/jogadores/{participante['link_id']}/composicao",
        json={"composicao_representacao_id": None,
              "composicao_unidades": [{"unidade_catalogo_id": unidade_tcg.id, "quantidade": 1}]},
        headers=headers,
    )
    assert r.status_code == 400
    assert "mesmo TCG" in r.json()["detail"]


def test_pontuacao_e_pareamento_de_torneio_vgc_funcionam_igual_ao_tcg(client: TestClient, session: Session):
    """A pontuação/desempate suíço não muda entre TCG e VGC — só a
    composição (sem representação) é diferente. Mesmo fluxo de
    test_routes_torneio.py, só que com jogo=POKEMON_VGC."""
    _, token = _criar_loja_autenticada(client, "Loja Pontuacao VGC", "loja.pontuacaovgc@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra = _criar_regra_vgc(client, headers)
    torneio = _criar_torneio_vgc(client, headers, regra["id"])

    vencedor = _adicionar_participante(session, torneio["id"], regra["id"], "Vencedor")
    perdedor = _adicionar_participante(session, torneio["id"], regra["id"], "Perdedor")

    r = client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "EM_ANDAMENTO"
    assert r.json()["jogo"] == "POKEMON_VGC"

    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    rodada_id = int(list(r.json().keys())[0])

    r = client.put(
        "/api/lojas/torneios/rodadas/finalizar",
        json=[{"id_rodada": rodada_id, "id_vencedor": vencedor["link_id"]}],
        headers=headers,
    )
    assert r.status_code == 200, r.text

    vencedor_link = session.get(JogadorTorneioLink, vencedor["link_id"])
    perdedor_link = session.get(JogadorTorneioLink, perdedor["link_id"])
    assert vencedor_link.pontuacao_com_regras == 3  # pt_vitoria, sem regra extra
    assert perdedor_link.pontuacao_com_regras == 0  # pt_derrota, sem regra extra

    # Desempate suíço (OMW%/OOMW%) só é calculado como parte do recálculo
    # completo (TorneioService.calcular_pontuacao), não no finalizar de uma
    # rodada avulsa — mesmo comportamento de um torneio de TCG. Confirma que
    # já funciona pra VGC hoje (ver JOGOS_FORMATO_SUICO em TorneioService.py)
    # sem exigir nenhuma mudança nova.
    r = client.post(
        f"/api/lojas/torneios/{torneio['id']}/recalcular-pontuacao",
        json={"regra_basica_id": regra["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    session.refresh(vencedor_link)
    session.refresh(perdedor_link)
    assert vencedor_link.porcentagem_vitorias_oponentes is not None
    assert perdedor_link.porcentagem_vitorias_oponentes is not None
