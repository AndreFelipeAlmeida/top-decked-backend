from fastapi import APIRouter, UploadFile, Depends
from sqlmodel import text
from typing import Annotated
from app.utils.TorneioUtil import retornar_torneio_completo, editar_torneio_regras, calcular_pontuacao, calcular_pontuacao_rodada, get_torneio_top
from app.utils.ImportacaoUtil import importar_torneio
from app.utils.RodadaUtil import nova_rodada
from app.schemas.Torneio import TorneioPublico, TorneioAtualizar
from app.models import Torneio, TorneioBase, JogadorTorneioLink, Jogador, StatusTorneio, Rodada
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.dependencies import retornar_loja_atual, retornar_jogador_atual, retornar_usuario_atual
from sqlmodel import select
from typing import Dict


router = APIRouter(
    prefix="/lojas/torneios",
    tags=["Torneios"])

@router.put("/rodadas/finalizar")
def finalizar_varias_rodadas(
    resultados: list[dict],
    session: SessionDep
):
    for item in resultados:
        rodada_id = item.get("id_rodada")
        vencedor_id = item.get("id_vencedor")

        rodada = session.get(Rodada, rodada_id)
        if not rodada:
            raise TopDeckedException.not_found(f"Rodada {rodada_id} não encontrada")

        if rodada.finalizada:
            raise TopDeckedException.bad_request(f"Rodada {rodada_id} já finalizada")

        torneio = session.get(Torneio, rodada.torneio_id)
        if not torneio:
            raise TopDeckedException.not_found("Torneio não encontrado")

        if vencedor_id is not None and vencedor_id not in [rodada.jogador1_id, rodada.jogador2_id]:
            raise TopDeckedException.bad_request(
                f"Jogador {vencedor_id} não pertence à rodada {rodada_id}"
            )

        rodada.vencedor = vencedor_id
        rodada.finalizada = True
        calcular_pontuacao_rodada(session, rodada, torneio.regra_basica)
        session.add(rodada)

    session.commit()
    top_ranking = get_torneio_top(session, torneio.id)

    return {"ranking": top_ranking}

@router.post("/importar", response_model=TorneioPublico)
def importar_torneios(session: SessionDep, arquivo: UploadFile, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    torneio = importar_torneio(session, arquivo, loja.id)
    session.refresh(torneio)

    torneio_completo = retornar_torneio_completo(session, torneio)
    return torneio_completo

@router.get("/loja", response_model=list[TorneioPublico])
def get_loja_torneios(session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    torneios = session.exec(select(Torneio).where(
        Torneio.loja_id == loja.id
    )).all()
    
    if not torneios:
        raise TopDeckedException.not_found("Nenhum torneio encontrado.")
    return [retornar_torneio_completo(session, torneio) for torneio in torneios]

@router.post("/{torneio_id}/importar", response_model=TorneioPublico)
def importar_torneios(session: SessionDep, arquivo: UploadFile, torneio_id: str, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")
    if not torneio.loja_id == loja.id:
        raise TopDeckedException.forbidden()
    
    session.delete(torneio)
    torneio = importar_torneio(session, arquivo, loja.id)
    session.refresh(torneio)

    torneio_completo = retornar_torneio_completo(session, torneio)
    return torneio_completo


@router.put("/{torneio_id}/iniciar", response_model=TorneioPublico)
def iniciar_torneio(session: SessionDep, torneio_id: str, 
                    loja: Annotated[TokenData, Depends(retornar_loja_atual)],
                    regra_basica_id: int | None = None,
                    regras_adicionais: Dict[str, int] | None = None, 
                    pontuacao_de_participacao: int | None = None
                    ):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")
    if not torneio.loja_id == loja.id:
        raise TopDeckedException.forbidden()
    if not torneio.status == StatusTorneio.ABERTO:
        raise TopDeckedException.bad_request("Torneio não pode ser iniciado")
    if not torneio.regra_basica_id:
        raise TopDeckedException.bad_request("Torneio está sem regra básica")
    
    if pontuacao_de_participacao:
        torneio.pontuacao_de_participacao = pontuacao_de_participacao
        
    torneio = editar_torneio_regras(session, torneio,
                                    regra_basica_id,
                                    regras_adicionais)
    
    torneio.status = StatusTorneio.EM_ANDAMENTO
    session.add(torneio)
    session.commit()
    session.refresh(torneio)

    torneio_completo = retornar_torneio_completo(session, torneio)
    return torneio_completo


@router.put("/{torneio_id}/finalizar", response_model=TorneioPublico)
def finalizar_torneio(session: SessionDep, torneio_id: str, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")
    if not torneio.loja_id == loja.id:
        raise TopDeckedException.forbidden()

    torneio.status = StatusTorneio.FINALIZADO
    session.add(torneio)
    session.commit()
    session.refresh(torneio)

    torneio_completo = retornar_torneio_completo(session, torneio)
    return torneio_completo


@router.post("/{torneio_id}/rodada")
def proxima_rodada(session: SessionDep, torneio_id: str, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")
    if not torneio.loja_id == loja.id:
        raise TopDeckedException.forbidden()
    if not torneio.status == StatusTorneio.EM_ANDAMENTO:
        raise TopDeckedException.bad_request("Torneio Não foi iniciado")
    
    rodada = nova_rodada(session, torneio)
    
    session.commit()
    return rodada

@router.post("/criar",response_model=TorneioPublico)
def criar_torneio(session:SessionDep, torneio: TorneioBase, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    novo_torneio = Torneio(
        **torneio.model_dump(),
        loja_id = loja.id,
    )
    session.add(novo_torneio)
    session.commit()
    session.refresh(novo_torneio)
    return retornar_torneio_completo(session, novo_torneio)


@router.put("/{torneio_id}", response_model=TorneioPublico)
def editar_torneio(session: SessionDep, 
                   torneio_id: str, 
                   torneio_atualizar: TorneioAtualizar, 
                   loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    torneio = session.get(Torneio, torneio_id)
    
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")
    if not torneio.loja_id == loja.id:
        raise TopDeckedException.forbidden()
        
    dados_para_atualizar = torneio_atualizar.model_dump(
            exclude={"regras_adicionais"}, exclude_unset=True)
    
    torneio = torneio.sqlmodel_update(dados_para_atualizar)
    session.add(torneio)

    if torneio_atualizar.regra_basica_id or torneio_atualizar.regras_adicionais:
        torneio = editar_torneio_regras(session, torneio, 
                                        torneio_atualizar.regra_basica_id, 
                                        torneio_atualizar.regras_adicionais)
    
        session.add(torneio)
        calcular_pontuacao(session, torneio)
    
    session.commit()
    session.refresh(torneio)
    return retornar_torneio_completo(session, torneio)


@router.delete("/", status_code=204)
def deletar_torneios(session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    session.exec(text("DELETE FROM rodada"))
    session.exec(text("DELETE FROM jogadortorneiolink"))
    session.exec(text("DELETE FROM torneio"))
    session.commit()


@router.get("/", response_model=list[TorneioPublico])
def get_torneios(session: SessionDep):
    torneios = session.exec(select(Torneio))
    return [retornar_torneio_completo(session, torneio) for torneio in torneios]



@router.get("/{torneio_id}", response_model=TorneioPublico)
def get_torneio_por_loja(
    torneio_id: str,
    session: SessionDep,
    _: Annotated[TokenData, Depends(retornar_usuario_atual)]
):
    torneio = session.exec(select(Torneio).where(
        Torneio.id == torneio_id,
    )).first()

    if not torneio:
        raise TopDeckedException.not_found("Torneio não encontrado.")

    return retornar_torneio_completo(session, torneio)

@router.post("/{torneio_id}/inscricao", response_model=JogadorTorneioLink)
def inscrever_jogador(session: SessionDep, torneio_id: str, token_data: Annotated[TokenData, Depends(retornar_jogador_atual)]):
    torneio = session.get(Torneio, torneio_id)
    jogador = session.get(Jogador, token_data.id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")
    if torneio.status == StatusTorneio.FINALIZADO:
        raise TopDeckedException.bad_request("Torneio já finalizado")
    if not jogador.pokemon_id:
        raise TopDeckedException.bad_request("Jogador não possui um Pokémon ID vinculado")
    
    link = session.get(JogadorTorneioLink, {"torneio_id" : torneio.id,
                                            "jogador_id": jogador.pokemon_id})
    if link:
        raise TopDeckedException.bad_request("Inscrição já realizada")
    
    inscricao = JogadorTorneioLink(
        jogador_id=jogador.pokemon_id,
        torneio_id=torneio.id,
        regra_basica_id=torneio.regra_basica_id if torneio.regra_basica_id else None,
    )
    
    session.add(inscricao)
    session.commit()
    session.refresh(inscricao)

    return inscricao

@router.delete("/{torneio_id}/inscricao", status_code=204)
def desinscrever_jogador(session: SessionDep, torneio_id: str, token_data: Annotated[TokenData, Depends(retornar_jogador_atual)]):
    torneio = session.get(Torneio, torneio_id)
    jogador = session.get(Jogador, token_data.id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")
    if torneio.status == StatusTorneio.FINALIZADO:
        raise TopDeckedException.bad_request("Torneio já finalizado")

    inscricao = session.exec(select(JogadorTorneioLink).where(
        JogadorTorneioLink.jogador_id == jogador.pokemon_id,
        JogadorTorneioLink.torneio_id == torneio.id
    )).first()

    if not inscricao:
        raise TopDeckedException.not_found("Inscrição não encontrada")

    session.delete(inscricao)
    session.commit()
