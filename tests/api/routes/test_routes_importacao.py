from datetime import date

from fastapi.testclient import TestClient

from app.core.db import get_session
from sqlmodel import Session, select

from app.models import JogadorCriado, Loja, Torneio
from app.utils.Enums import StatusAprovacaoLoja


def _login(client: TestClient, email: str, senha: str) -> str:
    r = client.post("/api/login/token", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return r.json()["access_token"]


def _criar_loja_autenticada(client: TestClient, nome: str, email: str, senha: str = "senha123") -> dict:
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
    return {"Authorization": f"Bearer {token}"}


def _tdf_com_nascimento(
    jogador1_userid: str,
    jogador2_userid: str,
    nascimento1: str = "02/27/1993",
    nascimento2: str = "02/27/2000",
) -> bytes:
    xml = f"""<?xml version="1.0"?>
<tournament>
  <data>
    <id></id>
    <name>Torneio Nascimento Teste</name>
    <city>Fortaleza</city>
    <state>CE</state>
    <roundtime>30</roundtime>
    <startdate>08/01/2026</startdate>
  </data>
  <players>
    <player userid="{jogador1_userid}">
      <firstname>Jogador</firstname>
      <lastname>Um</lastname>
      <birthdate>{nascimento1}</birthdate>
    </player>
    <player userid="{jogador2_userid}">
      <firstname>Jogador</firstname>
      <lastname>Dois</lastname>
      <birthdate>{nascimento2}</birthdate>
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


def test_import_preenche_data_nascimento_do_jogador_criado_na_criacao(
    client: TestClient, session: Session
) -> None:
    headers = _criar_loja_autenticada(client, "Loja Nascimento", "loja.nascimento@gmail.com")
    arquivo = _tdf_com_nascimento(
        "gid-nasc-1", "gid-nasc-2", nascimento1="02/27/1993", nascimento2="02/27/2000"
    )

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", arquivo, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    jc1 = session.exec(select(JogadorCriado).where(JogadorCriado.game_id == "gid-nasc-1")).first()
    jc2 = session.exec(select(JogadorCriado).where(JogadorCriado.game_id == "gid-nasc-2")).first()
    assert jc1.data_nascimento == date(1993, 2, 27)
    assert jc2.data_nascimento == date(2000, 2, 27)


def test_import_por_loja_grava_loja_id_e_datas_corretamente(
    client: TestClient, session: Session
) -> None:
    headers = _criar_loja_autenticada(client, "Loja Import Datas", "loja.importdatas@gmail.com")
    session_loja = session.exec(select(Loja).where(Loja.nome == "Loja Import Datas")).first()

    arquivo = _tdf_com_nascimento("gid-datas-1", "gid-datas-2")

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", arquivo, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    torneio_publico = r.json()

    assert torneio_publico["loja"]["id"] == session_loja.id
    assert torneio_publico["data_planejada"] == "2026-08-01"
    assert torneio_publico["inicio_real"].startswith("2026-08-01T10:00:00")
    assert torneio_publico["fim_real"].startswith("2026-08-01T10:00:00")

    torneio_db = session.get(Torneio, torneio_publico["id"])
    assert torneio_db.loja_id == session_loja.id


def test_import_repetido_nao_sobrescreve_data_nascimento_existente(
    client: TestClient, session: Session
) -> None:
    """'Se o jogador criado já existir, mantenha o valor antigo' — um
    segundo torneio importado com uma data de nascimento diferente pro
    mesmo game_id não pode alterar o que já foi gravado da primeira vez."""
    headers = _criar_loja_autenticada(client, "Loja Repetido", "loja.repetido@gmail.com")

    primeiro = _tdf_com_nascimento(
        "gid-rep-1", "gid-rep-2", nascimento1="02/27/1993", nascimento2="02/27/2000"
    )
    r1 = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio1.tdf", primeiro, "text/xml")},
        headers=headers,
    )
    assert r1.status_code == 200, r1.text

    # Segundo torneio, mesmos game_ids, data de nascimento DIFERENTE.
    segundo = _tdf_com_nascimento(
        "gid-rep-1", "gid-rep-2", nascimento1="01/01/1999", nascimento2="01/01/1999"
    )
    r2 = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio2.tdf", segundo, "text/xml")},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text

    jc1 = session.exec(select(JogadorCriado).where(JogadorCriado.game_id == "gid-rep-1")).first()
    jc2 = session.exec(select(JogadorCriado).where(JogadorCriado.game_id == "gid-rep-2")).first()
    assert jc1.data_nascimento == date(1993, 2, 27)
    assert jc2.data_nascimento == date(2000, 2, 27)


def test_import_sem_birthdate_deixa_data_nascimento_nula(client: TestClient, session: Session) -> None:
    headers = _criar_loja_autenticada(client, "Loja Sem Nascimento", "loja.semnascimento@gmail.com")
    xml = """<?xml version="1.0"?>
<tournament>
  <data>
    <id></id>
    <name>Torneio Sem Birthdate</name>
    <city>Fortaleza</city>
    <state>CE</state>
    <roundtime>30</roundtime>
    <startdate>08/01/2026</startdate>
  </data>
  <players>
    <player userid="gid-sem-nasc-1">
      <firstname>Jogador</firstname>
      <lastname>Um</lastname>
    </player>
    <player userid="gid-sem-nasc-2">
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
              <player1 userid="gid-sem-nasc-1" />
              <player2 userid="gid-sem-nasc-2" />
              <tablenumber>1</tablenumber>
              <timestamp>08/01/2026 10:00:00</timestamp>
            </match>
          </matches>
        </round>
      </rounds>
    </pod>
  </pods>
</tournament>""".encode("utf-8")

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", xml, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    jc1 = session.exec(select(JogadorCriado).where(JogadorCriado.game_id == "gid-sem-nasc-1")).first()
    assert jc1.data_nascimento is None


def _tdf_envelope(players_xml: str, match_xml: str) -> bytes:
    xml = f"""<?xml version="1.0"?>
<tournament>
  <data>
    <id></id>
    <name>Torneio Teste</name>
    <city>Fortaleza</city>
    <state>CE</state>
    <roundtime>30</roundtime>
    <startdate>08/01/2026</startdate>
  </data>
  <players>
    {players_xml}
  </players>
  <pods>
    <pod>
      <rounds>
        <round number="1">
          <matches>
            {match_xml}
          </matches>
        </round>
      </rounds>
    </pod>
  </pods>
</tournament>"""
    return xml.encode("utf-8")


_PLAYERS_PADRAO = """
    <player userid="gid-1"><firstname>Um</firstname><lastname>Teste</lastname></player>
    <player userid="gid-2"><firstname>Dois</firstname><lastname>Teste</lastname></player>
"""


def _match_normal(outcome: str) -> str:
    return f"""
    <match outcome="{outcome}">
      <player1 userid="gid-1" />
      <player2 userid="gid-2" />
      <tablenumber>1</tablenumber>
      <timestamp>08/01/2026 10:00:00</timestamp>
    </match>
    """


def test_import_outcome_3_registra_empate_sem_vencedor(client: TestClient, session: Session) -> None:
    """Regressão do bug relatado: outcome=3 (empate) não pode virar vitória
    do jogador 1 só porque o código antigo checava `!= 2` em vez de `== 1`."""
    from app.models import JogadorTorneioLink, Rodada

    headers = _criar_loja_autenticada(client, "Loja Empate", "loja.empate@gmail.com")
    xml = _tdf_envelope(_PLAYERS_PADRAO, _match_normal("3"))

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", xml, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    link1 = session.exec(
        select(JogadorTorneioLink).join(JogadorCriado).where(JogadorCriado.game_id == "gid-1")
    ).first()
    rodada = session.exec(select(Rodada).where(Rodada.torneio_id == r.json()["id"])).first()
    assert rodada.vencedor_id is None
    assert rodada.jogador1_id == link1.id


def test_import_outcome_5_registra_bye_com_jogador1_vencedor(client: TestClient, session: Session) -> None:
    from app.models import JogadorTorneioLink, Rodada

    headers = _criar_loja_autenticada(client, "Loja Bye Outcome", "loja.byeoutcome@gmail.com")
    match_bye = """
    <match outcome="5">
      <player userid="gid-1" />
      <tablenumber>1</tablenumber>
      <timestamp>08/01/2026 10:00:00</timestamp>
    </match>
    """
    xml = _tdf_envelope(_PLAYERS_PADRAO, match_bye)

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", xml, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    link1 = session.exec(
        select(JogadorTorneioLink).join(JogadorCriado).where(JogadorCriado.game_id == "gid-1")
    ).first()
    rodada = session.exec(select(Rodada).where(Rodada.torneio_id == r.json()["id"])).first()
    assert rodada.vencedor_id == link1.id
    assert rodada.jogador2_id is None


def test_import_outcome_nao_mapeado_e_rejeitado_com_mensagem_amigavel(client: TestClient) -> None:
    headers = _criar_loja_autenticada(client, "Loja Outcome Invalido", "loja.outcomeinvalido@gmail.com")
    xml = _tdf_envelope(_PLAYERS_PADRAO, _match_normal("4"))

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", xml, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "outcome=4" in detail
    assert "time de desenvolvimento" in detail


def test_import_sem_atributo_outcome_e_rejeitado(client: TestClient) -> None:
    headers = _criar_loja_autenticada(client, "Loja Sem Outcome", "loja.semoutcome@gmail.com")
    match_sem_outcome = """
    <match>
      <player1 userid="gid-1" />
      <player2 userid="gid-2" />
      <tablenumber>1</tablenumber>
      <timestamp>08/01/2026 10:00:00</timestamp>
    </match>
    """
    xml = _tdf_envelope(_PLAYERS_PADRAO, match_sem_outcome)

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", xml, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 400
    assert "outcome" in r.json()["detail"]


def test_import_jogador_da_partida_ausente_na_lista_de_jogadores_e_rejeitado(client: TestClient) -> None:
    """Um <match> referenciando um userid que não está em <players> — arquivo
    incompleto/corrompido — precisa de um erro claro, não um KeyError cru."""
    headers = _criar_loja_autenticada(client, "Loja Jogador Ausente", "loja.jogadorausente@gmail.com")
    match_com_fantasma = """
    <match outcome="1">
      <player1 userid="gid-1" />
      <player2 userid="gid-fantasma" />
      <tablenumber>1</tablenumber>
      <timestamp>08/01/2026 10:00:00</timestamp>
    </match>
    """
    xml = _tdf_envelope(_PLAYERS_PADRAO, match_com_fantasma)

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", xml, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 400
    assert "gid-fantasma" in r.json()["detail"]


def test_import_jogador_sem_userid_e_rejeitado(client: TestClient) -> None:
    headers = _criar_loja_autenticada(client, "Loja Sem Userid", "loja.semuserid@gmail.com")
    players_sem_userid = """
    <player><firstname>Sem</firstname><lastname>Userid</lastname></player>
    """
    xml = _tdf_envelope(players_sem_userid, _match_normal("1"))

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", xml, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 400
    assert "userid" in r.json()["detail"]


def test_import_sem_bloco_pods_e_rejeitado(client: TestClient) -> None:
    headers = _criar_loja_autenticada(client, "Loja Sem Pods", "loja.sempods@gmail.com")
    xml = """<?xml version="1.0"?>
<tournament>
  <data>
    <id></id>
    <name>Torneio Sem Pods</name>
    <city>Fortaleza</city>
    <state>CE</state>
    <roundtime>30</roundtime>
    <startdate>08/01/2026</startdate>
  </data>
  <players>
    <player userid="gid-1"><firstname>Um</firstname><lastname>Teste</lastname></player>
  </players>
</tournament>""".encode("utf-8")

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", xml, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 400
    assert "pods" in r.json()["detail"]


def test_import_sem_bloco_rounds_dentro_de_pod_e_rejeitado(client: TestClient) -> None:
    headers = _criar_loja_autenticada(client, "Loja Sem Rounds", "loja.semrounds@gmail.com")
    xml = """<?xml version="1.0"?>
<tournament>
  <data>
    <id></id>
    <name>Torneio Sem Rounds</name>
    <city>Fortaleza</city>
    <state>CE</state>
    <roundtime>30</roundtime>
    <startdate>08/01/2026</startdate>
  </data>
  <players>
    <player userid="gid-1"><firstname>Um</firstname><lastname>Teste</lastname></player>
  </players>
  <pods>
    <pod></pod>
  </pods>
</tournament>""".encode("utf-8")

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", xml, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 400
    assert "rounds" in r.json()["detail"]


def test_import_sem_bloco_matches_dentro_de_round_e_rejeitado(client: TestClient) -> None:
    headers = _criar_loja_autenticada(client, "Loja Sem Matches", "loja.semmatches@gmail.com")
    xml = """<?xml version="1.0"?>
<tournament>
  <data>
    <id></id>
    <name>Torneio Sem Matches</name>
    <city>Fortaleza</city>
    <state>CE</state>
    <roundtime>30</roundtime>
    <startdate>08/01/2026</startdate>
  </data>
  <players>
    <player userid="gid-1"><firstname>Um</firstname><lastname>Teste</lastname></player>
  </players>
  <pods>
    <pod>
      <rounds>
        <round number="1"></round>
      </rounds>
    </pod>
  </pods>
</tournament>""".encode("utf-8")

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", xml, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 400
    assert "matches" in r.json()["detail"]


def test_import_birthdate_malformada_nao_derruba_a_importacao(client: TestClient, session: Session) -> None:
    """Regressão: `_data_nascimento_importada` fazia `except TopDeckedException`
    — mas `TopDeckedException` não é uma classe de exceção de verdade (só um
    factory de HTTPException), então uma data de nascimento mal formada
    derrubava a importação inteira com um TypeError em vez de simplesmente
    ignorar o campo (que é o comportamento documentado/esperado)."""
    headers = _criar_loja_autenticada(client, "Loja Nascimento Invalido", "loja.nascinvalido@gmail.com")
    xml = """<?xml version="1.0"?>
<tournament>
  <data>
    <id></id>
    <name>Torneio Nascimento Invalido</name>
    <city>Fortaleza</city>
    <state>CE</state>
    <roundtime>30</roundtime>
    <startdate>08/01/2026</startdate>
  </data>
  <players>
    <player userid="gid-nasc-invalido">
      <firstname>Jogador</firstname>
      <lastname>Um</lastname>
      <birthdate>data-invalida</birthdate>
    </player>
  </players>
  <pods>
    <pod>
      <rounds>
        <round number="1">
          <matches>
            <match outcome="5">
              <player userid="gid-nasc-invalido" />
              <tablenumber>1</tablenumber>
              <timestamp>08/01/2026 10:00:00</timestamp>
            </match>
          </matches>
        </round>
      </rounds>
    </pod>
  </pods>
</tournament>""".encode("utf-8")

    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", xml, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    jc = session.exec(select(JogadorCriado).where(JogadorCriado.game_id == "gid-nasc-invalido")).first()
    assert jc.data_nascimento is None
