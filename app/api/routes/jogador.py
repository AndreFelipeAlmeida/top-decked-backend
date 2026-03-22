from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from sqlmodel import select
from app.schemas.Jogador import JogadorPublico, JogadorUpdate, JogadorCriar, JogadorLojaPublico
from app.core.db import SessionDep
from typing import Annotated, List
from app.core.security import TokenData
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.core.config import settings
from app.models import Usuario, Jogador, JogadorTorneioLink, Torneio, LojaJogadorLink
from app.utils.UsuarioUtil import verificar_novo_usuario
from app.utils.JogadorUtil import vincular_historico_e_creditos, calcular_estatisticas, retornar_historico_jogador, retornar_todas_rodadas
from app.utils.datetimeUtil import data_agora_brasil
from app.utils.emailUtil import criar_token_confirmacao, processar_ativacao_usuario
from app.dependencies import retornar_jogador_atual, retornar_loja_atual
from typing import Annotated
import os


router = APIRouter(
    prefix="/jogadores",
    tags=["Jogadores"])


@router.post("/", response_model=JogadorPublico)
async def create_jogador(jogador: JogadorCriar, session: SessionDep, request: Request):
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

    await processar_ativacao_usuario(db_jogador.usuario, request)

    session.add(db_jogador)
    session.commit()
    session.refresh(db_jogador)
    return db_jogador


@router.get("/estatisticas")
def get_estatisticas(session: SessionDep,
                     token_data: Annotated[TokenData, Depends(retornar_jogador_atual)]):
    jogador = session.get(Jogador, token_data.id)

    return calcular_estatisticas(session, jogador)


@router.get("/rodadas")
def retornar_rodadas(session: SessionDep,
                     token_data: Annotated[TokenData, Depends(retornar_jogador_atual)]):
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
                       token_data: Annotated[TokenData, Depends(retornar_jogador_atual)]):
    jogador = session.get(Jogador, token_data.id)

    return retornar_historico_jogador(session, jogador)


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


@router.get("/", response_model=list[JogadorPublico])
def get_jogadores(session: SessionDep):
    return session.exec(select(Jogador)).all()


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
                       token_data: Annotated[TokenData, Depends(retornar_jogador_atual)]):
    jogador = session.get(Jogador, token_data.id)

    inscricoes = session.exec(select(JogadorTorneioLink)
                              .where(JogadorTorneioLink.jogador_id == jogador.id)).all()

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