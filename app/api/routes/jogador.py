from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from sqlmodel import select
from app.schemas.Jogador import JogadorPublico, JogadorUpdate, JogadorCriar
from app.core.db import SessionDep, Carta
from typing import Annotated, List
from app.core.security import TokenData
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.models import Usuario, Jogador, JogadorTorneioLink
from app.utils.UsuarioUtil import verificar_novo_usuario
from app.utils.JogadorUtil import calcular_estatisticas, retornar_historico_jogador
from app.utils.datetimeUtil import data_agora_brasil
from app.utils.emailUtil import criar_token_confirmacao
from app.dependencies import retornar_jogador_atual
from typing import Annotated
import os

from app.core.security import fastmail
from fastapi_mail import MessageSchema

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
        telefone= jogador.telefone,
        data_nascimento= jogador.data_nascimento
    )
    session.add(db_jogador)
    session.commit()
    session.refresh(db_jogador)

    token = criar_token_confirmacao(db_jogador.usuario.email)
    link = f"{request.base_url}login/confirmar-email?token={token}"

    mensagem = MessageSchema(
        subject="Confirme seu email",
        recipients=[db_jogador.usuario.email],
        body=f"Clique para confirmar: {link}",
        subtype="plain"
    )

    await fastmail.send_message(mensagem)

    return db_jogador

@router.get("/cartas", response_model=List[Carta])
def listar_cartas(session: SessionDep):
    cartas = session.exec(select(Carta)).all()
    if not cartas:
        raise HTTPException(status_code=404, detail="Nenhuma carta encontrada")
    return cartas

@router.get("/estatisticas")
def get_estatisticas(session: SessionDep,
                     token_data: Annotated[TokenData, Depends(retornar_jogador_atual)]):
    jogador = session.get(Jogador, token_data.id)

    return calcular_estatisticas(session, jogador)

@router.get("/historico")
def retornar_historico(session: SessionDep,
                     token_data: Annotated[TokenData, Depends(retornar_jogador_atual)]):
    jogador = session.get(Jogador, token_data.id)

    return retornar_historico_jogador(session, jogador)

@router.get("/usuario/{usuario_id}", response_model=JogadorPublico)
def retornar_jogador_pelo_usuario(usuario_id: int, session: SessionDep):
    jogador = session.exec(select(Jogador).where(Jogador.usuario_id == usuario_id)).first()
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
def get_jogadores(session : SessionDep): 
    return session.exec(select(Jogador)).all()
    
@router.put("/", response_model=JogadorPublico)
def update_jogador(novo: JogadorUpdate,
                session: SessionDep, 
                token_data : Annotated[TokenData, Depends(retornar_jogador_atual)]):
    
    jogador = session.get(Jogador, token_data.id)
    
    if not jogador:
        raise TopDeckedException.not_found("Jogador nao encontrado")
    
    if novo.senha:
        jogador.usuario.set_senha(novo.senha)
        session.add(jogador.usuario)
        
    if novo.email:
        jogador.usuario.set_email(novo.email, session)
        session.add(jogador.usuario)
        
    if novo.pokemon_id:
        jogador_db = session.exec(select(Jogador)
                                  .where(Jogador.pokemon_id == novo.pokemon_id)).first()
        
        if jogador_db:
            jogador_db.nome = jogador.nome
            jogador_db.usuario_id = jogador.usuario_id
            session.delete(jogador)
            jogador = jogador_db

    jogador_data = novo.model_dump(exclude_unset=True, exclude={"senha"})
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
                              .where(JogadorTorneioLink.jogador_id == jogador.pokemon_id)).all()
    
    if not inscricoes:
        raise TopDeckedException.not_found("Jogador não se inscreveu em nenhum torneio")
    
    return inscricoes

@router.post("/upload_foto", response_model=JogadorPublico)
def update_foto(session: SessionDep, 
                token_data : Annotated[TokenData, Depends(retornar_jogador_atual)],
                file: UploadFile = File(None)):
    
    jogador = session.get(Jogador, token_data.id)
    
    if not jogador:
        raise TopDeckedException.not_found("Jogador nao encontrado")
    
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    if file:
        ext = file.filename.split(".")[-1]
        file_path = os.path.join(UPLOAD_DIR, f"user_{jogador.usuario.id}.{ext}")
        with open(file_path, "wb") as f:
            f.write(file.file.read())
        jogador.usuario.foto = f"user_{jogador.usuario.id}.{ext}"
        session.add(jogador.usuario)
        session.commit()
    return jogador

@router.put("/{jogador_id}/deck")
def adicionar_deck(
    session: SessionDep,
    jogador_id,
    torneio_id: str,
    cartas: list[dict]):
    jogador = session.get(Jogador, jogador_id)

    link = session.exec(
        select(JogadorTorneioLink)
        .where(JogadorTorneioLink.jogador_id == jogador.pokemon_id,
               JogadorTorneioLink.torneio_id == torneio_id)
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Jogador não inscrito nesse torneio")

    deck_atual = link.deck or []

    total_novo = sum(c['quantidade'] for c in cartas)
    total_atual = sum(c['quantidade'] for c in deck_atual)
    if total_novo + total_atual > 60:
        raise HTTPException(status_code=400, detail="O deck não pode ter mais que 60 cartas no total")

    for c in cartas:
        if c['quantidade'] > 4:
            raise HTTPException(status_code=400, detail=f"A carta {c['id_carta']} não pode ter mais que 4 cópias")
        existing = next((x for x in deck_atual if x['id_carta'] == c['id_carta']), None)
        if existing and existing['quantidade'] + c['quantidade'] > 4:
            raise HTTPException(status_code=400, detail=f"A carta {c['id_carta']} não pode ter mais que 4 cópias no deck")

    for c in cartas:
        existing = next((x for x in deck_atual if x['id_carta'] == c['id_carta']), None)
        if existing:
            existing['quantidade'] += c['quantidade']
        else:
            deck_atual.append(c)

    link.deck = deck_atual
    session.add(link)
    session.commit()
    session.refresh(link)

    return {"msg": "Deck atualizado com sucesso", "deck": link.deck}