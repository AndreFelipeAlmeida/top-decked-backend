from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlmodel import select
from app.schemas.Jogador import JogadorCompleto, JogadorPublico, JogadorUpdate, JogadorCriar, JogadorLojaPublico, PaginatedJogadores, ImpactoTrocaGameIdPublico
from app.core.db import SessionDep
from typing import Annotated
from app.core.security import TokenData
from app.core.exception import TopDeckedException
from app.models import Usuario, Jogador, JogadorTorneioLink, LojaJogadorLink, JogadorCriado
from app.utils.Enums import TCG
from app.services.UsuarioService import verificar_novo_usuario
from app.services.JogadorService import vincular_historico_e_creditos, calcular_estatisticas, retornar_historico_jogador, retornar_todas_rodadas, contar_impacto_troca_gameid
from app.services.ConquistaService import recalcular_conquistas_jogador
from app.utils.datetimeUtil import data_agora_brasil
from app.services.EmailService import processar_ativacao_usuario
from app.dependencies import retornar_jogador_atual, retornar_loja_atual, contexto_dominio, permitir_leitura_publica
import os


router = APIRouter(
    prefix="/jogadores",
    tags=["Jogadores"])


@router.post("/", response_model=JogadorPublico)
async def create_jogador(jogador: JogadorCriar, session: SessionDep):
    verificar_novo_usuario(jogador.email, session)
    novo_usuario = Usuario(
        email=jogador.email,
        tipo="jogador",
        data_cadastro=data_agora_brasil()
    )
    novo_usuario.set_senha(jogador.senha)
    session.add(novo_usuario)
    session.commit()
    session.refresh(novo_usuario)

    db_jogador = Jogador(
        nome=jogador.nome,
        usuario=novo_usuario,
    )

    await processar_ativacao_usuario(db_jogador.usuario)

    session.add(db_jogador)
    session.commit()
    session.refresh(db_jogador)
    return db_jogador

@router.get(
    "/me",
    response_model=JogadorCompleto
)
def retornar_meu_jogador(
    session: SessionDep,
    token_data: Annotated[
        TokenData,
        Depends(retornar_jogador_atual)
    ]
):
    jogador = session.exec(
        select(Jogador)
        .where(Jogador.id == token_data.id)
        .options(
            selectinload(Jogador.usuario),

            selectinload(Jogador.tcgs),

            selectinload(Jogador.lojas)
            .selectinload(LojaJogadorLink.loja),

            selectinload(Jogador.lojas)
            .selectinload(
                LojaJogadorLink.organizacoes
            )
        )
    ).first()

    if not jogador:
        raise TopDeckedException.not_found(
            "Jogador não encontrado"
        )
    return jogador

@router.get("/estatisticas")
def get_estatisticas(session: SessionDep,
                     token_data: Annotated[TokenData, Depends(retornar_jogador_atual)],
                     _leitura_publica: Annotated[None, Depends(permitir_leitura_publica)],
                     loja_id: Annotated[int | None, Depends(contexto_dominio)] = None,
                     tcg: str | None = None):
    jogador = session.get(Jogador, token_data.id)

    # dashboard do jogador filtra tudo pela loja do subdomínio
    # atual (contexto_dominio, resolvido pelo Host via TenantHostMiddleware)
    # — None no domínio raiz mantém as estatísticas globais de sempre.
    # tcg (query param opcional, mandado pelo front conforme o
    # jogo selecionado na barra lateral) filtra por jogo — None ("Todos os
    # jogos") agrega todos os TCGs.
    #
    # permitir_leitura_publica: as estatísticas agregam rodada/jogadortorneiolink
    # de TODAS as lojas em que o jogador já participou, não só uma — sem o
    # bypass, a policy de RLS ficaria fail-closed nesta transação sem tenant
    # único (ver dependencies.py).
    return calcular_estatisticas(session, jogador, loja_id=loja_id, tcg=tcg)


@router.get("/rodadas")
def retornar_rodadas(session: SessionDep,
                     token_data: Annotated[TokenData, Depends(retornar_jogador_atual)],
                     _leitura_publica: Annotated[None, Depends(permitir_leitura_publica)]):
    jogador = session.get(Jogador, token_data.id)

    return retornar_todas_rodadas(session, jogador)


@router.get("/loja", response_model=list[JogadorLojaPublico])
def get_jogadores_por_loja(session: SessionDep, token_data: Annotated[TokenData, Depends(retornar_loja_atual)]):
    statement = (
        select(Jogador, LojaJogadorLink.quantidade)
        .join(LojaJogadorLink, (LojaJogadorLink.loja_id == token_data.id) & (Jogador.id == LojaJogadorLink.jogador_id))
        .distinct()
    )

    results = session.exec(statement).all()

    jogadores_formatados = []
    for jogador, qtd_credito in results:
        jogador_data = jogador.model_dump()
        jogador_data["creditos"] = qtd_credito or 0
        jogadores_formatados.append(jogador_data)

    return jogadores_formatados


@router.get("/historico")
def retornar_historico(session: SessionDep,
                       token_data: Annotated[TokenData, Depends(retornar_jogador_atual)],
                       _leitura_publica: Annotated[None, Depends(permitir_leitura_publica)]):
    jogador = session.get(Jogador, token_data.id)

    return retornar_historico_jogador(session, jogador)


@router.get("/impacto-troca-gameid", response_model=ImpactoTrocaGameIdPublico)
def get_impacto_troca_gameid(
    session: SessionDep,
    tcg: TCG,
    token_data: Annotated[TokenData, Depends(retornar_jogador_atual)],
    _leitura_publica: Annotated[None, Depends(permitir_leitura_publica)],
):
    gameid_atual = session.exec(
        select(JogadorCriado).where(
            (JogadorCriado.jogador_id == token_data.id) & (JogadorCriado.tcg == tcg)
        )
    ).first()

    if not gameid_atual:
        return ImpactoTrocaGameIdPublico(
            tcg=tcg, game_id_atual=None, torneios_importados=0
        )

    torneios = contar_impacto_troca_gameid(session, token_data.id, tcg, gameid_atual.game_id)

    return ImpactoTrocaGameIdPublico(
        tcg=tcg,
        game_id_atual=gameid_atual.game_id,
        torneios_importados=torneios,
    )


@router.get("/usuario/{usuario_id}", response_model=JogadorPublico)
def retornar_jogador_pelo_usuario(usuario_id: int, session: SessionDep):
    jogador = session.exec(select(Jogador).where(
        Jogador.usuario_id == usuario_id)).first()
    if not jogador:
        raise TopDeckedException.not_found("Jogador nao encontrado")

    return jogador


@router.get("/{jogador_id}", response_model=JogadorPublico)
def retornar_jogador(jogador_id: int, session: SessionDep):
    jogador = session.get(Jogador, jogador_id)
    if not jogador:
        raise TopDeckedException.not_found("Jogador nao encontrado")

    return jogador


@router.get("/", response_model=PaginatedJogadores)
def get_jogadores(
    session: SessionDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: str | None = None,
):
    offset = (page - 1) * limit

    # lojas.organizacoes precisa vir eager-loaded: a tabela de "Gerenciar
    # Jogadores" (PlayersTable.tsx) decide se mostra "Promover" ou
    # "Despromover" com base nisso — sem eager load, a relação de segundo
    # nível não é carregada e o front nunca vê o estado atual (sempre
    # aparenta que ninguém é organizador).
    query = select(Jogador).options(
        selectinload(Jogador.tcgs),
        selectinload(Jogador.lojas).selectinload(LojaJogadorLink.organizacoes),
        selectinload(Jogador.lojas).selectinload(LojaJogadorLink.loja),
    )

    if search:
        query = query.where(
            or_(
                Jogador.nome.ilike(f"%{search}%"),
                Jogador.tcgs.any(JogadorCriado.game_id.ilike(f"%{search}%"))
            )
        )

    jogadores = session.exec(
        query.offset(offset).limit(limit)
    ).all()

    total = session.exec(
        select(func.count()).select_from(query.subquery())
    ).one()

    total_pages = (total + limit - 1) // limit

    return {
        "data": jogadores,
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
    }

@router.put("/", response_model=JogadorPublico)
def update_jogador(novo: JogadorUpdate,
                   session: SessionDep,
                   token_data: Annotated[TokenData, Depends(retornar_jogador_atual)]):

    jogador = session.get(Jogador, token_data.id)

    if not jogador:
        raise TopDeckedException.not_found("Jogador nao encontrado")

    if novo.senha:
        jogador.usuario.set_senha(novo.senha)
        session.add(jogador.usuario)

    if novo.email:
        jogador.usuario.set_email(novo.email, session)
        session.add(jogador.usuario)

    if novo.tcgs:
        vincular_historico_e_creditos(session, novo.tcgs, jogador.id)

    jogador_data = novo.model_dump(exclude_unset=True, exclude={"senha", "email"})
    jogador.sqlmodel_update(jogador_data)
    session.add(jogador)
    session.commit()
    session.refresh(jogador)

    if novo.tcgs:
        # Trocar/vincular um GameID pode ligar retroativamente todo um
        # histórico de torneios importados a este jogador (ver
        # vincular_historico_e_creditos) — sem isso, conquistas baseadas
        # nesse histórico (horas jogadas, torneios jogados, vitórias) só
        # seriam atualizadas na próxima vez que algo disparasse o recálculo
        # (ex.: finalizar um torneio novo), ficando visivelmente desatualizadas
        # até lá.
        recalcular_conquistas_jogador(session, jogador.id)

    return jogador


@router.delete("/{jogador_id}", status_code=204)
def delete_usuario(session: SessionDep,
                   jogador_id,
                   usuario: Annotated[TokenData, Depends(retornar_jogador_atual)]):
    jogador = session.get(Jogador, jogador_id)

    if not jogador:
        raise TopDeckedException.not_found("Jogador não encontrado")

    if jogador.usuario_id != usuario.usuario_id:
        raise TopDeckedException.forbidden()

    session.delete(jogador.usuario)
    session.commit()


@router.get("/torneios/inscritos")
def torneios_inscritos(session: SessionDep,
                       token_data: Annotated[TokenData, Depends(retornar_jogador_atual)],
                       _leitura_publica: Annotated[None, Depends(permitir_leitura_publica)]):
    jogador = session.get(Jogador, token_data.id)

    inscricoes = session.exec(
        select(JogadorTorneioLink)
        .join(JogadorCriado, JogadorCriado.id == JogadorTorneioLink.jogador_criado_id)
        .where(JogadorCriado.jogador_id == jogador.id)
    ).all()

    if not inscricoes:
        raise TopDeckedException.not_found(
            "Jogador não se inscreveu em nenhum torneio")

    return inscricoes


@router.post("/upload_foto", response_model=JogadorPublico)
def update_foto(session: SessionDep,
                token_data: Annotated[TokenData, Depends(retornar_jogador_atual)],
                file: UploadFile = File(None)):

    jogador = session.get(Jogador, token_data.id)

    if not jogador:
        raise TopDeckedException.not_found("Jogador nao encontrado")

    BASE_DIR = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    if file:
        ext = file.filename.split(".")[-1]
        file_path = os.path.join(
            UPLOAD_DIR, f"user_{jogador.usuario.id}.{ext}")
        with open(file_path, "wb") as f:
            f.write(file.file.read())
        jogador.usuario.foto = f"user_{jogador.usuario.id}.{ext}"
        session.add(jogador.usuario)
        session.commit()
    return jogador