"""Testes do sistema de Eventos (docs/EVENTOS.md): metas com recompensa,
regras de pontuação automáticas (observando torneios FINALIZADO do
período) e pontos manuais ("Outros Motivos"). Nada é armazenado como total —
pontos_automaticos/pontos_manuais/pontos_total são sempre recalculados na
hora a partir de JogadorTorneioLink + RegraPontuacaoEvento +
PontosManualEvento."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.core.db import get_session
from sqlmodel import Session, select

from app.models import (
    Loja,
    Evento,
    Jogador,
    JogadorCriado,
    JogadorTorneioLink,
    LojaJogadorLink,
    MetaEvento,
    ParticipanteEvento,
    PontosManualEvento,
    RegraPontuacaoEvento,
    Torneio,
    Usuario,
)
from app.utils.datetimeUtil import data_agora_brasil
from app.utils.Enums import TCG, TipoParticipanteTorneio, StatusAprovacaoLoja


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


def _criar_regra_torneio(client: TestClient, headers: dict, **overrides) -> dict:
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


def _criar_evento(client: TestClient, headers: dict, **overrides) -> dict:
    payload = {
        "tcg": "POKEMON",
        "nome": "Liga de Verão",
        "descricao": "Evento de teste",
        "data_inicio": "2026-08-01",
        "data_fim": "2026-08-31",
        **overrides,
    }
    r = client.post("/api/lojas/eventos/", json=payload, headers=headers)
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


def _adicionar_participante_torneio(session: Session, torneio_id: str, jogador_criado_id: int, apelido: str) -> int:
    link = JogadorTorneioLink(
        torneio_id=torneio_id, jogador_criado_id=jogador_criado_id, apelido=apelido,
        pontuacao=0, pontuacao_com_regras=0,
    )
    session.add(link)
    session.commit()
    session.refresh(link)
    return link.id


def _definir_inicio_real(session: Session, torneio_id: str, inicio_real: datetime) -> None:
    """Torneios FINALIZADO contam pros pontos automáticos de um Evento pela
    data efetiva (real), não a planejada — sem isso, `finalizar` preenche
    inicio_real com o "agora" do teste, que cai fora da janela do evento
    fixada nestes testes."""
    torneio = session.get(Torneio, torneio_id)
    torneio.inicio_real = inicio_real
    session.commit()


def test_criar_evento_e_status_calculado(client: TestClient) -> None:
    _, token = _criar_loja_autenticada(client, "Loja Evento 1", "loja.evento1@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    hoje = data_agora_brasil()
    evento = _criar_evento(
        client, headers,
        data_inicio=str(hoje.replace(day=1)),
        data_fim="2099-12-31",
    )
    assert evento["status"] == "ATIVO"

    r = client.get("/api/lojas/eventos/loja", headers=headers)
    assert r.status_code == 200, r.text
    assert any(e["id"] == evento["id"] for e in r.json())


def test_evento_agendado_e_encerrado(client: TestClient) -> None:
    _, token = _criar_loja_autenticada(client, "Loja Evento Status", "loja.eventostatus@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    agendado = _criar_evento(client, headers, nome="Futuro", data_inicio="2099-01-01", data_fim="2099-02-01")
    assert agendado["status"] == "AGENDADO"

    encerrado = _criar_evento(client, headers, nome="Passado", data_inicio="2020-01-01", data_fim="2020-02-01")
    assert encerrado["status"] == "ENCERRADO"


def test_evento_calcula_pontos_automaticos_por_regra(client: TestClient, session: Session) -> None:
    loja, token = _criar_loja_autenticada(client, "Loja Evento Pontos", "loja.eventopontos@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    evento = _criar_evento(client, headers, data_inicio="2026-08-01", data_fim="2026-08-31")

    r = client.post(f"/api/lojas/eventos/{evento['id']}/regras", json={"tipo": "VITORIA", "pontos": 2}, headers=headers)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/lojas/eventos/{evento['id']}/regras", json={"tipo": "PARTICIPACAO", "pontos": 1}, headers=headers)
    assert r.status_code == 200, r.text

    regra_basica = _criar_regra_torneio(client, headers)
    r = client.post(
        "/api/lojas/torneios/criar",
        json={"data_planejada": "2026-08-15", "jogo": "POKEMON", "formato": "PADRAO",
              "vagas": 8, "regra_basica_id": regra_basica["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    torneio = r.json()

    vencedor = _criar_jogador_da_loja(session, loja["id"], "Vencedor Evento")
    perdedor = _criar_jogador_da_loja(session, loja["id"], "Perdedor Evento")
    link_vencedor_id = _adicionar_participante_torneio(session, torneio["id"], vencedor["jogador_criado_id"], "Vencedor Evento")
    _adicionar_participante_torneio(session, torneio["id"], perdedor["jogador_criado_id"], "Perdedor Evento")

    client.put(f"/api/lojas/torneios/{torneio['id']}/iniciar", headers=headers)
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/rodada", headers=headers)
    assert r.status_code == 200, r.text
    rodada_id = int(list(r.json().keys())[0])

    r = client.put(
        "/api/lojas/torneios/rodadas/finalizar",
        json=[{"id_rodada": rodada_id, "id_vencedor": link_vencedor_id}],
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # calcular_desempate_suico (que preenche vitorias/derrotas) só roda no
    # recálculo completo, não no finalizar avulso — ver TorneioService.
    r = client.post(f"/api/lojas/torneios/{torneio['id']}/recalcular-pontuacao",
                     json={"regra_basica_id": regra_basica["id"]}, headers=headers)
    assert r.status_code == 200, r.text

    _definir_inicio_real(session, torneio["id"], datetime(2026, 8, 15, 10, 0, tzinfo=ZoneInfo("America/Fortaleza")))
    r = client.put(f"/api/lojas/torneios/{torneio['id']}/finalizar", headers=headers)
    assert r.status_code == 200, r.text

    client.post(f"/api/lojas/eventos/{evento['id']}/participantes",
                json={"jogador_criado_id": vencedor["jogador_criado_id"]}, headers=headers)
    client.post(f"/api/lojas/eventos/{evento['id']}/participantes",
                json={"jogador_criado_id": perdedor["jogador_criado_id"]}, headers=headers)

    r = client.get(f"/api/lojas/eventos/{evento['id']}", headers=headers)
    assert r.status_code == 200, r.text
    participantes_por_id = {p["jogador_criado_id"]: p for p in r.json()["participantes"]}

    # vencedor: participação(1) + vitória(2*1) = 3
    assert participantes_por_id[vencedor["jogador_criado_id"]]["pontos_automaticos"] == 3
    # perdedor: só participação(1), sem regra de derrota cadastrada
    assert participantes_por_id[perdedor["jogador_criado_id"]]["pontos_automaticos"] == 1


def test_torneio_fora_do_periodo_do_evento_nao_conta(client: TestClient, session: Session) -> None:
    loja, token = _criar_loja_autenticada(client, "Loja Evento Periodo", "loja.eventoperiodo@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    evento = _criar_evento(client, headers, data_inicio="2026-08-01", data_fim="2026-08-31")
    client.post(f"/api/lojas/eventos/{evento['id']}/regras", json={"tipo": "PARTICIPACAO", "pontos": 5}, headers=headers)

    regra_basica = _criar_regra_torneio(client, headers)
    r = client.post(
        "/api/lojas/torneios/criar",
        # Fora do período do evento (setembro, evento é em agosto).
        json={"data_planejada": "2026-09-15", "jogo": "POKEMON", "formato": "PADRAO",
              "vagas": 8, "regra_basica_id": regra_basica["id"]},
        headers=headers,
    )
    torneio = r.json()
    jogador = _criar_jogador_da_loja(session, loja["id"], "Fora Periodo")
    _adicionar_participante_torneio(session, torneio["id"], jogador["jogador_criado_id"], "Fora Periodo")
    client.put(f"/api/lojas/torneios/{torneio['id']}/finalizar", headers=headers)

    client.post(f"/api/lojas/eventos/{evento['id']}/participantes",
                json={"jogador_criado_id": jogador["jogador_criado_id"]}, headers=headers)

    r = client.get(f"/api/lojas/eventos/{evento['id']}", headers=headers)
    participante = r.json()["participantes"][0]
    assert participante["pontos_automaticos"] == 0


def test_torneio_no_dia_limite_do_evento_conta(client: TestClient, session: Session) -> None:
    """Limite inclusivo: um torneio finalizado exatamente no dia de início
    (ou fim) do evento precisa contar — não pode "sumir" por um bug de
    timezone/limite de hora nessa fronteira."""
    loja, token = _criar_loja_autenticada(client, "Loja Evento Limite", "loja.eventolimite@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    evento = _criar_evento(client, headers, data_inicio="2026-08-07", data_fim="2026-08-07")
    client.post(f"/api/lojas/eventos/{evento['id']}/regras", json={"tipo": "PARTICIPACAO", "pontos": 5}, headers=headers)

    regra_basica = _criar_regra_torneio(client, headers)
    r = client.post(
        "/api/lojas/torneios/criar",
        json={"data_planejada": "2026-08-07", "jogo": "POKEMON", "formato": "PADRAO",
              "vagas": 8, "regra_basica_id": regra_basica["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    torneio = r.json()
    jogador = _criar_jogador_da_loja(session, loja["id"], "No Limite")
    _adicionar_participante_torneio(session, torneio["id"], jogador["jogador_criado_id"], "No Limite")

    # Bem no fim do dia — o cenário clássico onde um limite exclusivo (ou um
    # deslocamento de fuso) faria o torneio cair fora do período.
    _definir_inicio_real(session, torneio["id"], datetime(2026, 8, 7, 23, 30, tzinfo=ZoneInfo("America/Fortaleza")))
    r = client.put(f"/api/lojas/torneios/{torneio['id']}/finalizar", headers=headers)
    assert r.status_code == 200, r.text

    client.post(f"/api/lojas/eventos/{evento['id']}/participantes",
                json={"jogador_criado_id": jogador["jogador_criado_id"]}, headers=headers)

    r = client.get(f"/api/lojas/eventos/{evento['id']}", headers=headers)
    participante = r.json()["participantes"][0]
    assert participante["pontos_automaticos"] == 5


def test_torneio_com_conta_em_eventos_false_nao_conta(client: TestClient, session: Session) -> None:
    """Torneio com a flag `conta_em_eventos=False` não deve somar pontos
    automáticos em nenhum Evento, mesmo finalizado dentro do período."""
    loja, token = _criar_loja_autenticada(client, "Loja Evento Flag", "loja.eventoflag@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    evento = _criar_evento(client, headers, data_inicio="2026-08-01", data_fim="2026-08-31")
    client.post(f"/api/lojas/eventos/{evento['id']}/regras", json={"tipo": "PARTICIPACAO", "pontos": 5}, headers=headers)

    regra_basica = _criar_regra_torneio(client, headers)
    r = client.post(
        "/api/lojas/torneios/criar",
        json={"data_planejada": "2026-08-15", "jogo": "POKEMON", "formato": "PADRAO",
              "vagas": 8, "regra_basica_id": regra_basica["id"], "conta_em_eventos": False},
        headers=headers,
    )
    torneio = r.json()
    assert torneio["conta_em_eventos"] is False

    jogador = _criar_jogador_da_loja(session, loja["id"], "Amistoso")
    _adicionar_participante_torneio(session, torneio["id"], jogador["jogador_criado_id"], "Amistoso")
    client.put(f"/api/lojas/torneios/{torneio['id']}/finalizar", headers=headers)

    client.post(f"/api/lojas/eventos/{evento['id']}/participantes",
                json={"jogador_criado_id": jogador["jogador_criado_id"]}, headers=headers)

    r = client.get(f"/api/lojas/eventos/{evento['id']}", headers=headers)
    participante = r.json()["participantes"][0]
    assert participante["pontos_automaticos"] == 0


def test_torneio_conta_em_eventos_default_true(client: TestClient, session: Session) -> None:
    """Criar um torneio sem informar a flag deve assumir True."""
    _, token = _criar_loja_autenticada(client, "Loja Evento Flag Default", "loja.eventoflagdefault@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    regra_basica = _criar_regra_torneio(client, headers)

    r = client.post(
        "/api/lojas/torneios/criar",
        json={"data_planejada": "2026-08-15", "jogo": "POKEMON", "formato": "PADRAO",
              "vagas": 8, "regra_basica_id": regra_basica["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["conta_em_eventos"] is True


def test_juiz_nao_pontua_automaticamente(client: TestClient, session: Session) -> None:
    loja, token = _criar_loja_autenticada(client, "Loja Evento Juiz", "loja.eventojuiz@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    evento = _criar_evento(client, headers, data_inicio="2026-08-01", data_fim="2026-08-31")
    client.post(f"/api/lojas/eventos/{evento['id']}/regras", json={"tipo": "PARTICIPACAO", "pontos": 5}, headers=headers)

    regra_basica = _criar_regra_torneio(client, headers)
    r = client.post(
        "/api/lojas/torneios/criar",
        json={"data_planejada": "2026-08-10", "jogo": "POKEMON", "formato": "PADRAO",
              "vagas": 8, "regra_basica_id": regra_basica["id"]},
        headers=headers,
    )
    torneio = r.json()
    juiz = _criar_jogador_da_loja(session, loja["id"], "Juiz Evento")

    link = JogadorTorneioLink(
        torneio_id=torneio["id"], jogador_criado_id=juiz["jogador_criado_id"], apelido="Juiz Evento",
        tipo=TipoParticipanteTorneio.JUIZ, pontuacao=0, pontuacao_com_regras=0,
    )
    session.add(link)
    session.commit()

    client.put(f"/api/lojas/torneios/{torneio['id']}/finalizar", headers=headers)
    client.post(f"/api/lojas/eventos/{evento['id']}/participantes",
                json={"jogador_criado_id": juiz["jogador_criado_id"]}, headers=headers)

    r = client.get(f"/api/lojas/eventos/{evento['id']}", headers=headers)
    participante = r.json()["participantes"][0]
    assert participante["pontos_automaticos"] == 0


def test_pontos_manuais_somam_no_participante(client: TestClient, session: Session) -> None:
    loja, token = _criar_loja_autenticada(client, "Loja Evento Manual", "loja.eventomanual@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    evento = _criar_evento(client, headers)
    jogador = _criar_jogador_da_loja(session, loja["id"], "Jogador Manual")
    r = client.post(f"/api/lojas/eventos/{evento['id']}/participantes",
                     json={"jogador_criado_id": jogador["jogador_criado_id"]}, headers=headers)
    assert r.status_code == 200, r.text

    r = client.post(
        f"/api/lojas/eventos/{evento['id']}/pontos-manuais",
        json={"jogador_criado_id": jogador["jogador_criado_id"], "descricao": "Ajudou na organização", "pontos": 4},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["pontos_manuais"] == 4
    assert r.json()["pontos_total"] == 4

    r = client.post(
        f"/api/lojas/eventos/{evento['id']}/pontos-manuais",
        json={"jogador_criado_id": jogador["jogador_criado_id"], "descricao": "Trouxe brinde", "pontos": 1},
        headers=headers,
    )
    assert r.json()["pontos_manuais"] == 5


def test_composicao_pontos_ordenada_cronologicamente_intercalando_automaticos_e_manuais(
    client: TestClient, session: Session,
) -> None:
    """composicao_pontos não é mais "automáticos primeiro, manuais depois"
    — é estritamente cronológica pelo momento em que cada pedaço foi ganho.
    Um ponto manual concedido numa data anterior à do torneio (mesmo tendo
    sido registrado via API depois do torneio já finalizado) deve aparecer
    ANTES do pedaço automático do torneio na lista."""
    loja, token = _criar_loja_autenticada(client, "Loja Evento Cronologia", "loja.eventocronologia@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    evento = _criar_evento(client, headers, data_inicio="2026-08-01", data_fim="2026-08-31")
    client.post(f"/api/lojas/eventos/{evento['id']}/regras", json={"tipo": "PARTICIPACAO", "pontos": 1}, headers=headers)

    regra_basica = _criar_regra_torneio(client, headers)
    r = client.post(
        "/api/lojas/torneios/criar",
        json={"data_planejada": "2026-08-20", "jogo": "POKEMON", "formato": "PADRAO",
              "vagas": 8, "regra_basica_id": regra_basica["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    torneio = r.json()

    jogador = _criar_jogador_da_loja(session, loja["id"], "Jogador Cronologia")
    _adicionar_participante_torneio(session, torneio["id"], jogador["jogador_criado_id"], "Jogador Cronologia")

    _definir_inicio_real(session, torneio["id"], datetime(2026, 8, 20, 10, 0, tzinfo=ZoneInfo("America/Fortaleza")))
    r = client.put(f"/api/lojas/torneios/{torneio['id']}/finalizar", headers=headers)
    assert r.status_code == 200, r.text

    client.post(f"/api/lojas/eventos/{evento['id']}/participantes",
                json={"jogador_criado_id": jogador["jogador_criado_id"]}, headers=headers)

    # Ponto manual registrado DEPOIS do torneio já finalizado (via API), mas
    # com um momento (criado_em) anterior ao dia do torneio.
    r = client.post(
        f"/api/lojas/eventos/{evento['id']}/pontos-manuais",
        json={"jogador_criado_id": jogador["jogador_criado_id"], "descricao": "Bônus antigo", "pontos": 2},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    registro = session.exec(
        select(PontosManualEvento).where(
            (PontosManualEvento.evento_id == evento["id"]) &
            (PontosManualEvento.jogador_criado_id == jogador["jogador_criado_id"])
        )
    ).one()
    registro.criado_em = datetime(2026, 8, 5, 9, 0, tzinfo=ZoneInfo("America/Fortaleza"))
    session.add(registro)
    session.commit()

    r = client.get(f"/api/lojas/eventos/{evento['id']}", headers=headers)
    assert r.status_code == 200, r.text
    participante = r.json()["participantes"][0]
    motivos = [pedaco["motivo"] for pedaco in participante["composicao_pontos"]]
    assert motivos == ["Bônus antigo", "Participação"]


def test_pontos_manuais_para_nao_participante_e_rejeitado(client: TestClient, session: Session) -> None:
    loja, token = _criar_loja_autenticada(client, "Loja Evento Manual Rejeitado", "loja.eventomanualrej@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    evento = _criar_evento(client, headers)
    jogador = _criar_jogador_da_loja(session, loja["id"], "Nao Participante")

    r = client.post(
        f"/api/lojas/eventos/{evento['id']}/pontos-manuais",
        json={"jogador_criado_id": jogador["jogador_criado_id"], "descricao": "X", "pontos": 1},
        headers=headers,
    )
    assert r.status_code == 404


def test_participante_duplicado_e_rejeitado(client: TestClient, session: Session) -> None:
    loja, token = _criar_loja_autenticada(client, "Loja Evento Duplicado", "loja.eventoduplicado@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    evento = _criar_evento(client, headers)
    jogador = _criar_jogador_da_loja(session, loja["id"], "Duplicado")

    r1 = client.post(f"/api/lojas/eventos/{evento['id']}/participantes",
                      json={"jogador_criado_id": jogador["jogador_criado_id"]}, headers=headers)
    assert r1.status_code == 200, r1.text

    r2 = client.post(f"/api/lojas/eventos/{evento['id']}/participantes",
                      json={"jogador_criado_id": jogador["jogador_criado_id"]}, headers=headers)
    assert r2.status_code == 400


def test_participante_de_tcg_diferente_e_rejeitado(client: TestClient, session: Session) -> None:
    loja, token = _criar_loja_autenticada(client, "Loja Evento TCG", "loja.eventotcg@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}

    evento = _criar_evento(client, headers, tcg="POKEMON")
    jogador_vgc = _criar_jogador_da_loja(session, loja["id"], "Jogador VGC", tcg=TCG.POKEMON_VGC)

    r = client.post(f"/api/lojas/eventos/{evento['id']}/participantes",
                     json={"jogador_criado_id": jogador_vgc["jogador_criado_id"]}, headers=headers)
    assert r.status_code == 400


def test_metas_retornadas_ordenadas_por_pontos(client: TestClient) -> None:
    _, token = _criar_loja_autenticada(client, "Loja Evento Metas", "loja.eventometas@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    evento = _criar_evento(client, headers)

    client.post(f"/api/lojas/eventos/{evento['id']}/metas",
                json={"pontos_necessarios": 20, "recompensa_descricao": "Playmat", "recompensa_imagem_url": None},
                headers=headers)
    client.post(f"/api/lojas/eventos/{evento['id']}/metas",
                json={"pontos_necessarios": 5, "recompensa_descricao": "Sleeves", "recompensa_imagem_url": None},
                headers=headers)

    r = client.get(f"/api/lojas/eventos/{evento['id']}", headers=headers)
    pontos = [m["pontos_necessarios"] for m in r.json()["metas"]]
    assert pontos == [5, 20]


def test_editar_e_excluir_regra(client: TestClient) -> None:
    _, token = _criar_loja_autenticada(client, "Loja Evento Regra Edit", "loja.eventoregraedit@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    evento = _criar_evento(client, headers)

    r = client.post(f"/api/lojas/eventos/{evento['id']}/regras", json={"tipo": "EMPATE", "pontos": 1}, headers=headers)
    regra_id = r.json()["id"]

    r = client.put(f"/api/lojas/eventos/{evento['id']}/regras/{regra_id}",
                    json={"tipo": "EMPATE", "pontos": 3}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["pontos"] == 3

    r = client.delete(f"/api/lojas/eventos/{evento['id']}/regras/{regra_id}", headers=headers)
    assert r.status_code == 204

    r = client.get(f"/api/lojas/eventos/{evento['id']}", headers=headers)
    assert r.json()["regras"] == []


def test_deletar_evento_remove_dependencias_em_cascata(client: TestClient, session: Session) -> None:
    loja, token = _criar_loja_autenticada(client, "Loja Evento Cascata", "loja.eventocascata@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    evento = _criar_evento(client, headers)
    evento_id = evento["id"]

    client.post(f"/api/lojas/eventos/{evento_id}/metas",
                json={"pontos_necessarios": 5, "recompensa_descricao": "X", "recompensa_imagem_url": None},
                headers=headers)
    client.post(f"/api/lojas/eventos/{evento_id}/regras", json={"tipo": "VITORIA", "pontos": 1}, headers=headers)
    jogador = _criar_jogador_da_loja(session, loja["id"], "Vai Sumir")
    client.post(f"/api/lojas/eventos/{evento_id}/participantes",
                json={"jogador_criado_id": jogador["jogador_criado_id"]}, headers=headers)
    client.post(f"/api/lojas/eventos/{evento_id}/pontos-manuais",
                json={"jogador_criado_id": jogador["jogador_criado_id"], "descricao": "X", "pontos": 1},
                headers=headers)

    r = client.delete(f"/api/lojas/eventos/{evento_id}", headers=headers)
    assert r.status_code == 204

    assert session.get(Evento, evento_id) is None
    assert session.exec(select(MetaEvento).where(MetaEvento.evento_id == evento_id)).first() is None
    assert session.exec(select(RegraPontuacaoEvento).where(RegraPontuacaoEvento.evento_id == evento_id)).first() is None
    assert session.exec(select(ParticipanteEvento).where(ParticipanteEvento.evento_id == evento_id)).first() is None
    assert session.exec(select(PontosManualEvento).where(PontosManualEvento.evento_id == evento_id)).first() is None


def test_permissao_negada_para_loja_diferente(client: TestClient) -> None:
    _, token_dono = _criar_loja_autenticada(client, "Loja Evento Dona", "loja.eventodona@gmail.com")
    headers_dono = {"Authorization": f"Bearer {token_dono}"}
    evento = _criar_evento(client, headers_dono)

    _, token_intruso = _criar_loja_autenticada(client, "Loja Evento Intrusa", "loja.eventointrusa@gmail.com")
    headers_intruso = {"Authorization": f"Bearer {token_intruso}"}

    r = client.delete(f"/api/lojas/eventos/{evento['id']}", headers=headers_intruso)
    assert r.status_code == 403


def test_jogadores_disponiveis_inclui_registrados_na_loja(client: TestClient, session: Session) -> None:
    loja, token = _criar_loja_autenticada(client, "Loja Evento Disponiveis", "loja.eventodisp@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    evento = _criar_evento(client, headers)

    jogador = _criar_jogador_da_loja(session, loja["id"], "Disponivel")

    r = client.get(f"/api/lojas/eventos/{evento['id']}/jogadores-disponiveis", headers=headers)
    assert r.status_code == 200, r.text
    ids = {j["id"] for j in r.json()}
    assert jogador["jogador_criado_id"] in ids


def test_jogadores_disponiveis_inclui_avulso_que_ja_jogou_na_loja(client: TestClient, session: Session) -> None:
    """Um JogadorCriado sem conta vinculada (jogador_id nulo — ex.: entrou só
    por import de .tdf) deve poder ser adicionado como participante de
    evento desde que já tenha jogado algum torneio desta loja."""
    loja, token = _criar_loja_autenticada(client, "Loja Evento Avulso", "loja.eventoavulso@gmail.com")
    headers = {"Authorization": f"Bearer {token}"}
    evento = _criar_evento(client, headers)

    regra_basica = _criar_regra_torneio(client, headers)
    r = client.post(
        "/api/lojas/torneios/criar",
        json={"data_planejada": "2026-08-10", "jogo": "POKEMON", "formato": "PADRAO",
              "vagas": 8, "regra_basica_id": regra_basica["id"]},
        headers=headers,
    )
    torneio = r.json()

    avulso = JogadorCriado(game_id="gid-avulso-sem-conta", tcg="POKEMON", jogador_id=None)
    session.add(avulso)
    session.commit()
    session.refresh(avulso)
    _adicionar_participante_torneio(session, torneio["id"], avulso.id, "Avulso Sem Conta")

    r = client.get(f"/api/lojas/eventos/{evento['id']}/jogadores-disponiveis", headers=headers)
    assert r.status_code == 200, r.text
    ids = {j["id"] for j in r.json()}
    assert avulso.id in ids

    r = client.post(
        f"/api/lojas/eventos/{evento['id']}/participantes",
        json={"jogador_criado_id": avulso.id},
        headers=headers,
    )
    assert r.status_code == 200, r.text


def test_novo_fluxo_criar_jogador_vincular_gameid_e_participar_conta_pontos(
    client: TestClient, session: Session,
) -> None:
    """Sequência "Criar Torneio -> Criar Jogador -> Vincular código Pokémon
    -> Adicionar como participante" — o jogador se autoinscreve num torneio
    já FINALIZADO logo após vincular o game_id (nunca teve LojaJogadorLink,
    já que quem criou a conta e vinculou foi ele mesmo, não a loja/import)."""
    loja, token_loja = _criar_loja_autenticada(client, "Loja Novo Fluxo", "loja.novofluxo@gmail.com")
    headers_loja = {"Authorization": f"Bearer {token_loja}"}

    evento = _criar_evento(client, headers_loja, data_inicio="2026-08-01", data_fim="2026-08-31")
    client.post(f"/api/lojas/eventos/{evento['id']}/regras", json={"tipo": "PARTICIPACAO", "pontos": 5}, headers=headers_loja)

    regra_basica = _criar_regra_torneio(client, headers_loja)
    r = client.post(
        "/api/lojas/torneios/criar",
        json={"data_planejada": "2026-08-10", "jogo": "POKEMON", "formato": "PADRAO",
              "vagas": 8, "regra_basica_id": regra_basica["id"]},
        headers=headers_loja,
    )
    assert r.status_code == 200, r.text
    torneio = r.json()

    # "Criar Jogador"
    r = client.post("/api/jogadores/", json={"nome": "Ash", "email": "ash.novofluxo@gmail.com", "senha": "senha123"})
    assert r.status_code == 200, r.text
    token_jogador = _login(client, "ash.novofluxo@gmail.com", "senha123")
    headers_jogador = {"Authorization": f"Bearer {token_jogador}"}

    # "Vincular código Pokémon" — sem nenhum LojaJogadorLink com esta loja.
    r = client.put(
        "/api/jogadores/",
        json={"tcgs": [{"tcg": "POKEMON", "id": "ash-novo-fluxo"}]},
        headers=headers_jogador,
    )
    assert r.status_code == 200, r.text
    jogador_criado_id = r.json()["tcgs"][0]["id"]

    r = client.post(f"/api/lojas/torneios/{torneio['id']}/inscricao", headers=headers_jogador)
    assert r.status_code == 200, r.text
    _definir_inicio_real(session, torneio["id"], datetime(2026, 8, 10, 10, 0, tzinfo=ZoneInfo("America/Fortaleza")))
    client.put(f"/api/lojas/torneios/{torneio['id']}/finalizar", headers=headers_loja)

    r = client.get(f"/api/lojas/eventos/{evento['id']}/jogadores-disponiveis", headers=headers_loja)
    assert r.status_code == 200, r.text
    assert jogador_criado_id in {j["id"] for j in r.json()}

    # "Adicionar como participante"
    r = client.post(
        f"/api/lojas/eventos/{evento['id']}/participantes",
        json={"jogador_criado_id": jogador_criado_id},
        headers=headers_loja,
    )
    assert r.status_code == 200, r.text

    r = client.get(f"/api/lojas/eventos/{evento['id']}", headers=headers_loja)
    participante = r.json()["participantes"][0]
    assert participante["pontos_automaticos"] == 5
