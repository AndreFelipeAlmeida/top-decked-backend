from fastapi.testclient import TestClient

from app.core.db import get_session
from sqlmodel import Session, select

from app.models import Conquista, Jogador, JogadorCriado, JogadorTorneioLink, Loja, Rodada, Torneio, Usuario
from app.services.ConquistaService import _CATALOGO_SEMENTE, seed_conquistas_catalogo
from app.utils.Enums import CategoriaConquista, StatusAprovacaoLoja, TCG
from app.utils.datetimeUtil import data_agora_brasil


def _login(client: TestClient, email: str, senha: str) -> str:
    r = client.post("/api/login/token", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
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


def _criar_jogador_autenticado(client: TestClient, nome: str, email: str, senha: str = "senha123") -> tuple[dict, str]:
    r = client.post("/api/jogadores/", json={"nome": nome, "email": email, "senha": senha})
    assert r.status_code == 200, r.text
    token = _login(client, email, senha)
    return r.json(), token


def _criar_regra(client: TestClient, headers: dict, tcg: str) -> dict:
    payload = {
        "nome": f"Regra {tcg}", "pt_vitoria": 3, "pt_derrota": 0, "pt_empate": 1,
        "pt_oponente_ganha": 2, "pt_oponente_perde": -1, "pt_oponente_empate": 0, "tcg": tcg,
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


def _jogador_vence_torneio(session: Session, torneio_id: str, jogador_id: int, tcg: TCG, sufixo: str) -> None:
    """Cria (via session direta, bypassando o fluxo real de inscrição e
    pareamento) uma participação de `jogador_id` num torneio de `tcg`, com
    uma rodada em que ele é o vencedor — o mínimo pra exercitar as três
    categorias de conquista (horas, torneios jogados, vitórias)."""
    jogador_criado = JogadorCriado(game_id=f"gid-{sufixo}", tcg=tcg, jogador_id=jogador_id)
    session.add(jogador_criado)
    session.commit()
    session.refresh(jogador_criado)

    loja_id = session.get(Torneio, torneio_id).loja_id
    link = JogadorTorneioLink(
        torneio_id=torneio_id, loja_id=loja_id, jogador_criado_id=jogador_criado.id,
        pontuacao=0, pontuacao_com_regras=0,
    )
    session.add(link)
    session.commit()
    session.refresh(link)

    rodada = Rodada(
        torneio_id=torneio_id, loja_id=loja_id, num_rodada=1, mesa=1,
        jogador1_id=link.id, jogador2_id=None, vencedor_id=link.id,
        finalizada=True, data_de_inicio=data_agora_brasil(),
    )
    session.add(rodada)
    session.commit()


def test_seed_conquistas_catalogo_cria_uma_conquista_por_tcg(session: Session):
    seed_conquistas_catalogo(session)

    conquistas = session.exec(select(Conquista).where(Conquista.ativa == True)).all()
    assert len(conquistas) == len(_CATALOGO_SEMENTE) * len(TCG)

    for tcg in TCG:
        codigos_do_tcg = {c.codigo for c in conquistas if c.tcg == tcg}
        assert codigos_do_tcg == {f"{d['codigo_base']}_{tcg.value}" for d in _CATALOGO_SEMENTE}


def test_seed_conquistas_catalogo_e_idempotente(session: Session):
    seed_conquistas_catalogo(session)
    total_apos_primeira_chamada = len(session.exec(select(Conquista)).all())

    seed_conquistas_catalogo(session)
    total_apos_segunda_chamada = len(session.exec(select(Conquista)).all())

    assert total_apos_primeira_chamada == total_apos_segunda_chamada


def test_seed_desativa_catalogo_global_legado(session: Session):
    legada = Conquista(
        codigo="VITORIAS", nome="Vencedor", descricao="Vença partidas em torneios",
        categoria=CategoriaConquista.VITORIAS, icone="🏆", tcg=None, ativa=True,
    )
    session.add(legada)
    session.commit()
    session.refresh(legada)

    seed_conquistas_catalogo(session)

    session.refresh(legada)
    assert legada.ativa is False


def test_conquista_de_vitorias_so_soma_torneios_do_mesmo_tcg(client: TestClient, session: Session):
    seed_conquistas_catalogo(session)

    loja, loja_token = _criar_loja_autenticada(client, "Loja Conquistas", "loja.conquistas@gmail.com")
    loja_headers = {"Authorization": f"Bearer {loja_token}"}
    jogador, jogador_token = _criar_jogador_autenticado(client, "Ana", "ana.conquistas@gmail.com")
    jogador_headers = {"Authorization": f"Bearer {jogador_token}"}

    regra_tcg = _criar_regra(client, loja_headers, "POKEMON")
    torneio_tcg = _criar_torneio(client, loja_headers, regra_tcg["id"], "POKEMON")
    _jogador_vence_torneio(session, torneio_tcg["id"], jogador["id"], TCG.POKEMON, "tcg")
    client.put(f"/api/lojas/torneios/{torneio_tcg['id']}/finalizar", headers=loja_headers)

    regra_go = _criar_regra(client, loja_headers, "POKEMON_GO")
    torneio_go = _criar_torneio(client, loja_headers, regra_go["id"], "POKEMON_GO")
    _jogador_vence_torneio(session, torneio_go["id"], jogador["id"], TCG.POKEMON_GO, "go")
    client.put(f"/api/lojas/torneios/{torneio_go['id']}/finalizar", headers=loja_headers)

    r = client.post("/api/jogadores/conquistas/recalcular", headers=jogador_headers)
    assert r.status_code == 200, r.text

    r = client.get("/api/jogadores/conquistas", headers=jogador_headers)
    assert r.status_code == 200, r.text
    por_codigo = {item["conquista"]["codigo"]: item for item in r.json()}

    assert por_codigo["VITORIAS_POKEMON"]["progresso_atual"] == 1
    assert por_codigo["VITORIAS_POKEMON_GO"]["progresso_atual"] == 1
    assert por_codigo["VITORIAS_ONEPIECE"]["progresso_atual"] == 0
    assert por_codigo["VITORIAS_POKEMON_VGC"]["progresso_atual"] == 0

    assert por_codigo["TORNEIOS_JOGADOS_POKEMON"]["progresso_atual"] == 1
    assert por_codigo["TORNEIOS_JOGADOS_POKEMON_GO"]["progresso_atual"] == 1
