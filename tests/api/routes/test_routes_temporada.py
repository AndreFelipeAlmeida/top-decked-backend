"""Testes de Temporada Pokémon: CRUD + cálculo de categoria de idade —
ver docs/TEMPORADAS.md."""

from datetime import date

from fastapi.testclient import TestClient

from app.core.db import get_session

from app.models import Temporada, Loja, Jogador, JogadorCriado, JogadorTorneioLink, LojaJogadorLink, Usuario
from app.utils.CategoriaUtil import (
    calcular_categoria_por_idade,
    calcular_idade_na_data,
    calcular_categoria_na_temporada,
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


def _criar_loja_autenticada(client: TestClient, nome: str, email: str, senha: str = "senha123") -> tuple[dict, dict]:
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
    return r.json(), {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Cálculo puro de idade/categoria — o exemplo exato do pedido do usuário:
# temporada Set/2026-Ago/2027, aniversário em maio faz o jogador virar 17
# ainda dentro da temporada, então ele já entra como Master.
# ---------------------------------------------------------------------------

def test_calcular_categoria_por_idade_seguindo_os_cortes_oficiais():
    assert calcular_categoria_por_idade(12) == "Junior"
    assert calcular_categoria_por_idade(13) == "Senior"
    assert calcular_categoria_por_idade(16) == "Senior"
    assert calcular_categoria_por_idade(17) == "Master"
    assert calcular_categoria_por_idade(30) == "Master"


def test_exemplo_do_pedido_aniversario_no_meio_da_temporada_conta_a_idade_nova():
    """Exemplo exato do pedido: 'Em Setembro eu tenho 16 anos, mas em maio
    eu completo 17. Então, para o pokemon (como a temporada está setada de
    Setembro-Agosto), eu já tenho 17 anos e vou participar da categoria de
    17 anos (Master)' — 16 anos é Senior (13-16), 17 é Master (17+), então
    esse nascimento cruza a fronteira Senior/Master dentro da mesma
    temporada, e a temporada inteira precisa contar como Master."""
    nascimento = date(2010, 5, 15)  # 16 anos em set/2026, 17 anos a partir de mai/2027

    idade_no_inicio_da_temporada = calcular_idade_na_data(nascimento, date(2026, 9, 1))
    assert idade_no_inicio_da_temporada == 16
    assert calcular_categoria_por_idade(idade_no_inicio_da_temporada) == "Senior"

    temporada = Temporada(
        id=1, loja_id=1, tcg="POKEMON",
        ano_inicio=2026, mes_inicio=9, ano_fim=2027, mes_fim=8,
    )
    categoria = calcular_categoria_na_temporada(nascimento, temporada)
    # Último dia da temporada: 31/08/2027 -> already 17 (nasceu 15/05).
    idade_no_fim = calcular_idade_na_data(nascimento, date(2027, 8, 31))
    assert idade_no_fim == 17
    assert categoria == "Master"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_loja_cria_e_lista_temporada(client: TestClient):
    _, headers = _criar_loja_autenticada(client, "Loja Temporada", "loja.temporada@gmail.com")

    r = client.post(
        "/api/lojas/temporadas/",
        json={"tcg": "POKEMON", "nome": "2026-2027", "ano_inicio": 2026, "mes_inicio": 9, "ano_fim": 2027, "mes_fim": 8},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "2026-2027"

    r = client.get("/api/lojas/temporadas/", headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["tcg"] == "POKEMON"


def test_criar_temporada_rejeita_mes_fora_do_intervalo(client: TestClient):
    _, headers = _criar_loja_autenticada(client, "Loja Mes Invalido", "loja.mesinvalido@gmail.com")

    r = client.post(
        "/api/lojas/temporadas/",
        json={"tcg": "POKEMON", "ano_inicio": 2026, "mes_inicio": 13, "ano_fim": 2027, "mes_fim": 8},
        headers=headers,
    )
    assert r.status_code == 422


def test_criar_temporada_rejeita_fim_antes_do_inicio(client: TestClient):
    _, headers = _criar_loja_autenticada(client, "Loja Intervalo Invertido", "loja.invertido@gmail.com")

    r = client.post(
        "/api/lojas/temporadas/",
        json={"tcg": "POKEMON", "ano_inicio": 2027, "mes_inicio": 9, "ano_fim": 2026, "mes_fim": 8},
        headers=headers,
    )
    assert r.status_code == 422


def test_deletar_temporada(client: TestClient):
    _, headers = _criar_loja_autenticada(client, "Loja Deletar Temporada", "loja.deletartemporada@gmail.com")

    r = client.post(
        "/api/lojas/temporadas/",
        json={"tcg": "POKEMON", "ano_inicio": 2026, "mes_inicio": 9, "ano_fim": 2027, "mes_fim": 8},
        headers=headers,
    )
    temporada_id = r.json()["id"]

    r = client.delete(f"/api/lojas/temporadas/{temporada_id}", headers=headers)
    assert r.status_code == 204

    r = client.get("/api/lojas/temporadas/", headers=headers)
    assert r.json() == []


def test_deletar_temporada_de_outra_loja_e_rejeitado(client: TestClient):
    _, headers_a = _criar_loja_autenticada(client, "Loja A Temporada", "loja.a.temporada@gmail.com")
    _, headers_b = _criar_loja_autenticada(client, "Loja B Temporada", "loja.b.temporada@gmail.com")

    r = client.post(
        "/api/lojas/temporadas/",
        json={"tcg": "POKEMON", "ano_inicio": 2026, "mes_inicio": 9, "ano_fim": 2027, "mes_fim": 8},
        headers=headers_a,
    )
    temporada_id = r.json()["id"]

    # 403 (não 404): mesma semântica de verificar_permissao_gerenciar_torneio
    # /verificar_permissao_evento — a temporada existe, só não pertence a quem
    # está pedindo pra apagar.
    r = client.delete(f"/api/lojas/temporadas/{temporada_id}", headers=headers_b)
    assert r.status_code == 403


def test_organizador_deleta_temporada_da_loja_que_organiza(client: TestClient) -> None:
    """Espelha a mesma regra de permissão dual usada em torneios e eventos:
    um jogador-organizador consegue gerenciar (aqui, excluir) as temporadas
    da loja que ele organiza, não só a própria loja com token dela."""
    loja, headers_loja = _criar_loja_autenticada(client, "Loja Organizador Temp", "loja.organizadortemp@gmail.com")
    jogador, headers_jogador = _criar_jogador_autenticado(client, "Organizador Temp", "organizadortemp@gmail.com")

    session = client.app.dependency_overrides[get_session]()
    session.add(LojaJogadorLink(jogador_id=jogador["id"], loja_id=loja["id"], apelido="Organizador Temp"))
    session.commit()

    r = client.post(
        f"/api/lojas/jogador/{jogador['id']}/promover",
        json={"tcg": "POKEMON"},
        headers=headers_loja,
    )
    assert r.status_code == 200, r.text

    r = client.post(
        "/api/lojas/temporadas/organizador",
        json={"tcg": "POKEMON", "ano_inicio": 2026, "mes_inicio": 9, "ano_fim": 2027, "mes_fim": 8, "loja_id": loja["id"]},
        headers=headers_jogador,
    )
    assert r.status_code == 200, r.text
    temporada_id = r.json()["id"]

    r = client.delete(f"/api/lojas/temporadas/{temporada_id}", headers=headers_jogador)
    assert r.status_code == 204, r.text

    r = client.get("/api/lojas/temporadas/", headers=headers_loja)
    assert r.json() == []


def test_jogador_nao_organizador_nao_deleta_temporada_da_loja(client: TestClient) -> None:
    loja, headers_loja = _criar_loja_autenticada(client, "Loja Sem Organizador Temp", "loja.semorganizadortemp@gmail.com")
    _, headers_jogador = _criar_jogador_autenticado(client, "Nao Organizador", "naoorganizador@gmail.com")

    r = client.post(
        "/api/lojas/temporadas/",
        json={"tcg": "POKEMON", "ano_inicio": 2026, "mes_inicio": 9, "ano_fim": 2027, "mes_fim": 8},
        headers=headers_loja,
    )
    temporada_id = r.json()["id"]

    r = client.delete(f"/api/lojas/temporadas/{temporada_id}", headers=headers_jogador)
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Integração: torneio importado dentro de uma temporada expõe a categoria
# calculada em JogadorTorneioLinkPublico.
# ---------------------------------------------------------------------------

def _tdf(jogador1_userid: str, jogador2_userid: str, nascimento1: str, nascimento2: str, data_torneio: str) -> bytes:
    xml = f"""<?xml version="1.0"?>
<tournament>
  <data>
    <id></id>
    <name>Torneio Temporada Teste</name>
    <city>Fortaleza</city>
    <state>CE</state>
    <roundtime>30</roundtime>
    <startdate>{data_torneio}</startdate>
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
              <timestamp>{data_torneio} 10:00:00</timestamp>
            </match>
          </matches>
        </round>
      </rounds>
    </pod>
  </pods>
</tournament>"""
    return xml.encode("utf-8")


def test_torneio_dentro_da_temporada_expoe_categoria_calculada(client: TestClient):
    _, headers = _criar_loja_autenticada(client, "Loja Categoria Integrada", "loja.categoriaintegrada@gmail.com")

    client.post(
        "/api/lojas/temporadas/",
        json={"tcg": "POKEMON", "ano_inicio": 2026, "mes_inicio": 9, "ano_fim": 2027, "mes_fim": 8},
        headers=headers,
    )

    # Torneio em maio/2027 (dentro da temporada set/2026-ago/2027).
    # Jogador 1 nasceu em 15/05/2010 -> 17 anos até o fim da temporada (Master).
    # Jogador 2 nasceu em 15/05/2012 -> 15 anos até o fim da temporada (Senior).
    arquivo = _tdf("gid-temp-1", "gid-temp-2", "05/15/2010", "05/15/2012", "05/15/2027")
    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", arquivo, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    jogadores = {j["game_id"]: j for j in r.json()["jogadores"]}
    assert jogadores["gid-temp-1"]["categoria"] == "Master"
    assert jogadores["gid-temp-2"]["categoria"] == "Senior"


def test_torneio_fora_de_qualquer_temporada_tem_categoria_nula(client: TestClient):
    _, headers = _criar_loja_autenticada(client, "Loja Sem Temporada", "loja.semtemporada@gmail.com")

    # Nenhuma temporada cadastrada — categoria deve vir None mesmo com data
    # de nascimento presente.
    arquivo = _tdf("gid-notemp-1", "gid-notemp-2", "05/15/2010", "05/15/2016", "05/15/2027")
    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", arquivo, "text/xml")},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    for jogador in r.json()["jogadores"]:
        assert jogador["categoria"] is None


def test_categoria_usa_data_real_apos_finalizar_nao_a_planejada(client: TestClient) -> None:
    """A temporada (e a categoria) de um torneio FINALIZADO é decidida pela
    data real (inicio_real), nunca mais pela planejada — mesmo que a
    planejada tivesse ficado fora de qualquer temporada cadastrada."""
    loja, headers = _criar_loja_autenticada(client, "Loja Categoria Data Real", "loja.catdatareal@gmail.com")
    session = client.app.dependency_overrides[get_session]()

    client.post(
        "/api/lojas/temporadas/",
        json={"tcg": "POKEMON", "ano_inicio": 2026, "mes_inicio": 9, "ano_fim": 2027, "mes_fim": 8},
        headers=headers,
    )

    # data_planejada em out/2027 -- fora da temporada (que termina ago/2027).
    r = client.post(
        "/api/lojas/torneios/criar",
        json={"data_planejada": "2027-10-15", "jogo": "POKEMON", "formato": "PADRAO", "vagas": 8},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    torneio = r.json()

    usuario = Usuario(email="jogador.catdatareal@gmail.com", tipo="jogador",
                      is_active=True, data_cadastro=data_agora_brasil())
    usuario.set_senha("senha123")
    session.add(usuario)
    session.commit()
    session.refresh(usuario)

    jogador = Jogador(nome="Jogador Categoria", usuario_id=usuario.id)
    session.add(jogador)
    session.commit()
    session.refresh(jogador)

    # Nasceu em 15/05/2010 -> 17 anos completos até o fim da temporada
    # (ago/2027) -> Master.
    jogador_criado = JogadorCriado(game_id="gid-catdatareal", tcg=TCG.POKEMON,
                                   jogador_id=jogador.id, data_nascimento=date(2010, 5, 15))
    session.add(jogador_criado)
    session.commit()
    session.refresh(jogador_criado)

    session.add(JogadorTorneioLink(
        torneio_id=torneio["id"], loja_id=torneio["loja"]["id"], jogador_criado_id=jogador_criado.id,
        apelido="Jogador Categoria", pontuacao=0, pontuacao_com_regras=0,
    ))
    session.commit()

    # inicio_real em maio/2027 -- dentro da temporada.
    r = client.put(
        f"/api/lojas/torneios/{torneio['id']}",
        json={"inicio_real": "2027-05-15T10:00:00"},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    r = client.put(f"/api/lojas/torneios/{torneio['id']}/finalizar", headers=headers)
    assert r.status_code == 200, r.text

    r = client.get(f"/api/lojas/torneios/{torneio['id']}", headers=headers)
    assert r.status_code == 200, r.text
    jogadores = {j["game_id"]: j for j in r.json()["jogadores"]}
    assert jogadores["gid-catdatareal"]["categoria"] == "Master"


def _criar_jogador_autenticado(client: TestClient, nome: str, email: str, senha: str = "senha123") -> tuple[dict, dict]:
    r = client.post("/api/jogadores/", json={"nome": nome, "email": email, "senha": senha})
    assert r.status_code == 200, r.text
    token = _login(client, email, senha)
    return r.json(), {"Authorization": f"Bearer {token}"}


def test_categoria_usa_nascimento_da_conta_real_quando_jogador_criado_nao_tem(client: TestClient) -> None:
    """'Utilize a data de nascimento em jogador criado, se não tiver,
    utilize a data de nascimento do jogador em si (se ele existir)' — o
    jogador reivindica o game_id (sem nenhum <birthdate> vindo de import
    nenhum) e cadastra a própria data de nascimento no perfil; a categoria
    ainda deve ser calculada a partir dela."""
    _, headers_loja = _criar_loja_autenticada(client, "Loja Fallback Nascimento", "loja.fallbacknasc@gmail.com")
    jogador, headers_jogador = _criar_jogador_autenticado(client, "Fallback", "fallback.nasc@gmail.com")

    # Reivindica o game_id (cria o JogadorCriado sem data_nascimento própria).
    r = client.put(
        "/api/jogadores/",
        json={"tcgs": [{"tcg": "POKEMON", "id": "gid-fallback-nasc"}]},
        headers=headers_jogador,
    )
    assert r.status_code == 200, r.text

    # Cadastra a própria data de nascimento no perfil da conta real.
    r = client.put(
        "/api/jogadores/",
        json={"nome": "Fallback", "data_nascimento": "2010-05-15"},
        headers=headers_jogador,
    )
    assert r.status_code == 200, r.text

    client.post(
        "/api/lojas/temporadas/",
        json={"tcg": "POKEMON", "ano_inicio": 2026, "mes_inicio": 9, "ano_fim": 2027, "mes_fim": 8},
        headers=headers_loja,
    )

    # Importa um torneio em maio/2027 SEM <birthdate> (JogadorCriado já
    # existe — reivindicado acima — então o import não sobrescreve nada).
    arquivo = _tdf_sem_nascimento("gid-fallback-nasc", "gid-outro-sem-conta", "05/15/2027")
    r = client.post(
        "/api/lojas/torneios/importar",
        files={"arquivo": ("torneio.tdf", arquivo, "text/xml")},
        headers=headers_loja,
    )
    assert r.status_code == 200, r.text

    jogadores = {j["game_id"]: j for j in r.json()["jogadores"]}
    # 15/05/2010 -> 17 anos até 31/08/2027 -> Master.
    assert jogadores["gid-fallback-nasc"]["categoria"] == "Master"
    # Sem JogadorCriado.data_nascimento nem conta vinculada -> None.
    assert jogadores["gid-outro-sem-conta"]["categoria"] is None


def _tdf_sem_nascimento(jogador1_userid: str, jogador2_userid: str, data_torneio: str) -> bytes:
    xml = f"""<?xml version="1.0"?>
<tournament>
  <data>
    <id></id>
    <name>Torneio Fallback Nascimento</name>
    <city>Fortaleza</city>
    <state>CE</state>
    <roundtime>30</roundtime>
    <startdate>{data_torneio}</startdate>
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
              <timestamp>{data_torneio} 10:00:00</timestamp>
            </match>
          </matches>
        </round>
      </rounds>
    </pod>
  </pods>
</tournament>"""
    return xml.encode("utf-8")
