from fastapi import APIRouter, Depends, UploadFile, File, Request
import os
from typing import Annotated
from sqlalchemy import JSON, func
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.schemas.Loja import LojaCriar, LojaPublico, LojaAtualizar, LojaPublicoTorneios
from app.models import Loja, Torneio
from app.models import Usuario
from sqlmodel import select
from app.utils.UsuarioUtil import verificar_novo_usuario
from app.utils.emailUtil import criar_token_confirmacao
from app.utils.datetimeUtil import data_agora_brasil
from app.core.security import TokenData
from app.dependencies import retornar_loja_atual
from datetime import datetime

from app.core.security import fastmail
from fastapi_mail import MessageSchema
from app.utils.Enums import StatusTorneio

router = APIRouter(
    prefix="/lojas",
    tags=["Lojas"])

@router.post("/", response_model=LojaPublico)
async def criar_loja(loja: LojaCriar, session: SessionDep, request: Request):
    verificar_novo_usuario(loja.email, session)
    
    novo_usuario = Usuario(
        email=loja.email,
        tipo="loja",
        data_cadastro=data_agora_brasil()
    )
    novo_usuario.set_senha(loja.senha)
    
    session.add(novo_usuario)
    session.commit()
    session.refresh(novo_usuario)

    db_loja = Loja(
        nome=loja.nome,
        endereco=loja.endereco,
        telefone=loja.telefone,
        site=loja.site,
        usuario=novo_usuario
    )
    
    session.add(db_loja)
    session.commit()
    session.refresh(db_loja)

    token = criar_token_confirmacao(db_loja.usuario.email)
    link = f"{request.base_url}login/confirmar-email?token={token}"

    mensagem = MessageSchema(
        subject="Confirme seu email",
        recipients=[db_loja.usuario.email],
        body = (
            "Olá!\n\n"
            "Obrigado por se cadastrar na TopDecked.\n"
            "Para ativar sua conta, confirme seu e-mail clicando no link abaixo:\n\n"
            f"{link}\n\n"
            "Se você não criou uma conta, ignore esta mensagem.\n\n"
            "Atenciosamente,\n"
            "Equipe TopDecked"
        ),
        subtype="plain"
    )

    await fastmail.send_message(mensagem)

    return db_loja


@router.get("/", response_model=list[LojaPublicoTorneios])
def retornar_lojas(session: SessionDep):
    lojas = session.exec(select(Loja)).all()

    resultado = []
    for loja in lojas:
        qtd_torneios = session.scalar(select(func.count(Torneio.id))
                                      .where((Torneio.loja_id == loja.id)
                                  & (Torneio.status == StatusTorneio.FINALIZADO)))

        loja_publico = LojaPublicoTorneios.model_validate(loja)

        loja_publico.n_torneios = qtd_torneios
        resultado.append(loja_publico)

    return resultado


@router.get("/{loja_id}", response_model=LojaPublico)
def retornar_loja(loja_id: int, session: SessionDep):
    loja = session.get(Loja, loja_id)
    if not loja:
        raise TopDeckedException.not_found("Loja não encontrada")
    return loja


@router.put("/", response_model=LojaPublico)
def atualizar_loja(token_data: Annotated[TokenData, Depends(retornar_loja_atual)], loja_atualizar: LojaAtualizar, session: SessionDep):
    loja_db = session.get(Loja, token_data.id)
    
    if not loja_db:
        raise TopDeckedException.not_found("Loja não encontrada")

    if loja_atualizar.email:
        loja_db.usuario.set_email(loja_atualizar.email, session)
    if loja_atualizar.senha:
        loja_db.usuario.set_senha(loja_atualizar.senha)
        
    session.add(loja_db.usuario)

    loja_data = loja_atualizar.model_dump(exclude_unset=True, exclude={"senha", "email"})
    loja_db.sqlmodel_update(loja_data)
    session.add(loja_db)
    session.commit()
    session.refresh(loja_db)
    
    return loja_db

@router.delete("/{loja_id}")
def apagar_loja(loja_id: int, session: SessionDep):
    loja = session.get(Loja, loja_id)
    if not loja:
        raise TopDeckedException.not_found("Loja não encontrada")
    session.delete(loja)
    session.commit()
    return {"ok": True}

@router.post("/upload_foto", response_model=LojaPublico)
def update_foto(session: SessionDep, 
                token_data : Annotated[TokenData, Depends(retornar_loja_atual)],
                file: UploadFile = File(None)):
    
    loja = session.get(Loja, token_data.id)
    
    if not loja:
        raise TopDeckedException.not_found("Loja nao encontrado")
    
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    if file:
        ext = file.filename.split(".")[-1]
        file_path = os.path.join(UPLOAD_DIR, f"user_{loja.usuario.id}.{ext}")
        with open(file_path, "wb") as f:
            f.write(file.file.read())
        loja.usuario.foto = f"user_{loja.usuario.id}.{ext}"
        session.add(loja.usuario)
        session.commit()
    return loja

@router.get("/usuario/{usuario_id}", response_model=LojaPublico)
def retornar_jogador_pelo_usuario(usuario_id: int, session: SessionDep):
    jogador = session.exec(select(Loja).where(Loja.usuario_id == usuario_id)).first()
    if not jogador:
        raise TopDeckedException.not_found("Loja nao encontrado")
    
    return jogador  

@router.post("/upload_banner", response_model=LojaPublico)
def update_banner(session: SessionDep, 
                token_data : Annotated[TokenData, Depends(retornar_loja_atual)],
                file: UploadFile = File(None)):
    
    loja = session.get(Loja, token_data.id)
    
    if not loja:
        raise TopDeckedException.not_found("Loja nao encontrado")
    
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    if file:
        ext = file.filename.split(".")[-1]
        file_path = os.path.join(UPLOAD_DIR, f"user_{loja.usuario.id}_banner.{ext}")
        with open(file_path, "wb") as f:
            f.write(file.file.read())
        loja.banner = f"user_{loja.usuario.id}_banner.{ext}"
        session.add(loja.usuario)
        session.commit()
    return loja
