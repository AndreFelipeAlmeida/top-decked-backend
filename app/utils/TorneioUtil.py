from sqlmodel import select
from app.core.db import SessionDep
from app.models import Rodada, Torneio, Jogador, JogadorTorneioLink, TipoJogador

def retornar_torneio_completo(session: SessionDep, torneio: Torneio):
    torneio_dict = torneio.model_dump()
    
    torneio_dict["loja"] = torneio.loja
    torneio_dict["jogadores"] = []
    for link in torneio.jogadores:
        torneio_dict["jogadores"].append(
            {
                "jogador_id": link.jogador_id,
                "nome": link.jogador.nome,
                "tipo_jogador_id": link.tipo_jogador_id,
                "pontuacao": link.pontuacao,
                "pontuacao_com_regras": link.pontuacao_com_regras
            })

    torneio_dict["rodadas"] = [
        {
            "jogador1_id": rodada.jogador1_id,
            "jogador2_id": rodada.jogador2_id,
            "vencedor": rodada.vencedor,
            "num_rodada": rodada.num_rodada,
            "mesa": rodada.mesa,
            "data_de_inicio": rodada.data_de_inicio
        }
        for rodada in torneio.rodadas
    ]

    
    return torneio_dict


def editar_torneio_regras(session: SessionDep, torneio: Torneio, regra_basica: int, regras_adicionais: dict):
    torneio.regra_basica_id = regra_basica
    
    for jogador in torneio.jogadores:
        jogador.pontuacao = 0
        jogador.pontuacao_com_regras = torneio.pontuacao_de_participacao
        jogador_id = jogador.jogador_id
        
        if regras_adicionais and jogador_id in regras_adicionais:
            jogador.tipo_jogador_id = regras_adicionais[jogador_id]
        else:
            jogador.tipo_jogador_id = regra_basica
        session.add(jogador)
    return torneio


def calcular_pontuacao(session: SessionDep, torneio: Torneio):
    regra_basica = torneio.regra_basica
    
    for rodada in torneio.rodadas:
        calcular_pontuacao_rodada(session,rodada,regra_basica)

def calcular_pontuacao_rodada(session: SessionDep, rodada: Rodada, regra_basica: TipoJogador):
    jogador1_id = rodada.jogador1_id
    jogador2_id = rodada.jogador2_id
    jogador1_link = session.get(JogadorTorneioLink, {"torneio_id": rodada.torneio_id,
                                                        "jogador_id": jogador1_id})
    jogador2_link = session.get(JogadorTorneioLink, {"torneio_id": rodada.torneio_id,
                                                        "jogador_id": jogador2_id})
    jogador1_tipo = jogador1_link.tipo_jogador
    jogador2_tipo = TipoJogador(pt_vitoria=0, pt_derrota=0, pt_empate=0, pt_oponente_empate=0, pt_oponente_ganha=0, pt_oponente_perde=0)
    if jogador2_link:
        jogador2_tipo = jogador2_link.tipo_jogador

    if rodada.vencedor == jogador1_id:
        # Jogador 1 ganha os pontos por vitória 
        # e os pontos da regra de derrota do oponente
        jogador1_link.pontuacao_com_regras += (jogador1_tipo.pt_vitoria 
                                            + jogador2_tipo.pt_oponente_ganha)
        # Jogador 2 ganha os pontos por derrota 
        # e os pontos da regra de vitória do oponente (possivelmente negativos)
        if jogador2_link:
            jogador2_link.pontuacao_com_regras += (jogador2_tipo.pt_derrota
                                                    + jogador1_tipo.pt_oponente_perde)

        jogador1_link.pontuacao += (regra_basica.pt_vitoria
                                        + regra_basica.pt_oponente_ganha)
        
        if jogador2_link:
            jogador2_link.pontuacao += (regra_basica.pt_derrota
                                            + regra_basica.pt_oponente_perde)
        
    elif rodada.vencedor == jogador2_id:
        # Jogador 2 ganha os pontos por vitória
        # e os pontos da regra de derrota do oponente
        if jogador2_link:
            jogador2_link.pontuacao_com_regras += (jogador2_tipo.pt_vitoria
                                            + jogador1_tipo.pt_oponente_ganha)
        # Jogador 1 ganha os pontos por derrota
        # e os pontos da regra de vitória do oponente (possivelmente negativos)
        jogador1_link.pontuacao_com_regras += (jogador1_tipo.pt_derrota
                                            + jogador2_tipo.pt_oponente_perde)
        if jogador2_link:
            jogador2_link.pontuacao += (regra_basica.pt_vitoria
                                                + regra_basica.pt_oponente_ganha)
        
        jogador1_link.pontuacao += (regra_basica.pt_derrota
                                    + regra_basica.pt_oponente_perde)
    else:
        # Jogador 1 ganha os pontos por empate
        # e os pontos da regra de empate do oponente
        jogador1_link.pontuacao_com_regras += (jogador1_tipo.pt_empate
                                            + jogador2_tipo.pt_oponente_empate)
        # Jogador 2 ganha os pontos por empate
        # e os pontos da regra de empate do oponente
        if jogador2_link:
            jogador2_link.pontuacao_com_regras += (jogador2_tipo.pt_empate
                                            + jogador1_tipo.pt_oponente_empate)
        
        jogador1_link.pontuacao += (regra_basica.pt_empate
                                    + regra_basica.pt_oponente_empate)
        if jogador2_link:
            jogador2_link.pontuacao += (regra_basica.pt_empate
                                    + regra_basica.pt_oponente_empate)
    
    session.add(jogador1_link)
    if jogador2_link:
        session.add(jogador2_link)

def get_torneio_top(session: SessionDep, torneio_id: str):
    jogadores = session.exec(
        select(JogadorTorneioLink)
        .where(JogadorTorneioLink.torneio_id == torneio_id)
        .order_by(JogadorTorneioLink.pontuacao.desc())
    ).all()

    ranking = []
    for posicao, jt in enumerate(jogadores, start=1):
        jogador = session.get(Jogador, jt.jogador_id)
        ranking.append({
            "posicao": posicao,
            "jogador_nome": jogador.nome if jogador else None,
            "pontuacao": jt.pontuacao,
            "pontuacao_com_regras": jt.pontuacao_com_regras
        })

    return ranking