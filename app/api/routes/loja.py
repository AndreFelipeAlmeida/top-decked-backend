from fastapi import APIRouter, Depends, UploadFile, File, Request
import os
from typing import Annotated
from sqlalchemy import func
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.schemas.Loja import LojaCriar, LojaPublico, LojaAtualizar, LojaPublicoTorneios
from app.schemas.LojaJogadorLink import PromoverOrganizadorDTO
from app.models import Loja, Torneio, Usuario, Categoria, LojaJogadorLink, LojaJogadorOrganizadorTCG
from sqlmodel import select
from app.services.UsuarioService import verificar_novo_usuario
from app.services.EmailService import processar_ativacao_usuario
from app.utils.datetimeUtil import data_agora_brasil
from app.core.security import TokenData
from app.dependencies import retornar_loja_atual, retornar_usuario_atual_opcional

from app.utils.Enums import StatusTorneio, StatusAprovacaoLoja
from app.utils.SlugUtil import slugify

router = APIRouter(
    prefix="/lojas",
    tags=["Lojas"])


def _gerar_slug_unico(session: SessionDep, nome: str) -> str:
    """Resolve colisão com um sufixo numérico determinístico (BRK-305) —
    "Evolution Games" e outra loja chamada igual não podem colidir no
    mesmo subdomínio."""
    base = slugify(nome)
    slug = base
    sufixo = 2
    while session.exec(select(Loja).where(Loja.slug == slug)).first():
        slug = f"{base}-{sufixo}"
        sufixo += 1
    return slug


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
        slug=_gerar_slug_unico(session, loja.nome),
        usuario=novo_usuario
    )

    await processar_ativacao_usuario(db_loja.usuario, request)

    session.add(db_loja)
    session.commit()
    session.refresh(db_loja)
    
    session.add(Categoria(loja_id=db_loja.id, nome="Gerais"))
    session.commit()

    return db_loja


@router.get("/", response_model=list[LojaPublicoTorneios])
def retornar_lojas(
    session: SessionDep,
    token_data: Annotated[TokenData | None, Depends(retornar_usuario_atual_opcional)] = None,
):
    # BRK-403: página de diretório é pública, mas só faz sentido divulgar
    # lojas já aprovadas — PENDENTE/REJEITADA não são "descobríveis"
    # publicamente (a própria loja não tem nem subdomínio funcional ainda).
    lojas = session.exec(select(Loja).where(Loja.status == StatusAprovacaoLoja.APROVADA)).all()

    # Cross-referência com os vínculos do próprio jogador (se logado) pra
    # marcar em quais lojas ele já é organizador e em quais TCGs — GET
    # /lojas/ nunca exige login, isso só enriquece a resposta quando dá.
    tcgs_por_loja: dict[int, list[str]] = {}
    if token_data and token_data.tipo == "jogador":
        links = session.exec(
            select(LojaJogadorLink).where(LojaJogadorLink.jogador_id == token_data.id)
        ).all()
        for link in links:
            if link.loja_id is None or not link.organizacoes:
                continue
            tcgs_por_loja[link.loja_id] = [org.tcg for org in link.organizacoes]

    resultado = []
    for loja in lojas:
        qtd_torneios = session.scalar(select(func.count(Torneio.id))
                                      .where((Torneio.loja_id == loja.id)
                                             & (Torneio.status == StatusTorneio.FINALIZADO)))

        loja_publico = LojaPublicoTorneios.model_validate(loja)

        loja_publico.n_torneios = qtd_torneios
        loja_publico.tcgs_organizados = tcgs_por_loja.get(loja.id, [])
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

    loja_data = loja_atualizar.model_dump(
        exclude_unset=True, exclude={"senha", "email"})
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
                token_data: Annotated[TokenData, Depends(retornar_loja_atual)],
                file: UploadFile = File(None)):

    loja = session.get(Loja, token_data.id)

    if not loja:
        raise TopDeckedException.not_found("Loja nao encontrado")

    BASE_DIR = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
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
    loja = session.exec(select(Loja).where(
        Loja.usuario_id == usuario_id)).first()
    if not loja:
        raise TopDeckedException.not_found("Loja não encontrada")

    return loja


@router.post(
    "/jogador/{jogador_id}/promover",
    response_model=LojaJogadorOrganizadorTCG
)
def promover_jogador(
    session: SessionDep,
    token_data: Annotated[TokenData, Depends(retornar_loja_atual)],
    jogador_id: int,
    body: PromoverOrganizadorDTO
):

    link = session.exec(
        select(LojaJogadorLink)
        .where(
            (LojaJogadorLink.loja_id == token_data.id) &
            (LojaJogadorLink.jogador_id == jogador_id)
        )
    ).first()

    if not link:
        raise TopDeckedException.not_found("Jogador não encontrado")

    organizador_existente = session.exec(
        select(LojaJogadorOrganizadorTCG)
        .where(
            (LojaJogadorOrganizadorTCG.loja_jogador_link_id == link.id) &
            (LojaJogadorOrganizadorTCG.tcg == body.tcg)
        )
    ).first()

    if organizador_existente:
        raise TopDeckedException.bad_request(
            f"Jogador já é organizador de {body.tcg}"
        )

    organizador = LojaJogadorOrganizadorTCG(
        loja_jogador_link_id=link.id,
        tcg=body.tcg
    )

    session.add(organizador)
    session.commit()
    session.refresh(organizador)

    return organizador


@router.delete(
    "/jogador/{jogador_id}/despromover",
    response_model=LojaJogadorOrganizadorTCG
)
def despromover_jogador(
    session: SessionDep,
    token_data: Annotated[TokenData, Depends(retornar_loja_atual)],
    jogador_id: int,
    body: PromoverOrganizadorDTO
):

    link = session.exec(
        select(LojaJogadorLink)
        .where(
            (LojaJogadorLink.loja_id == token_data.id) &
            (LojaJogadorLink.jogador_id == jogador_id)
        )
    ).first()

    if not link:
        raise TopDeckedException.not_found("Jogador não encontrado")

    organizador = session.exec(
        select(LojaJogadorOrganizadorTCG)
        .where(
            (LojaJogadorOrganizadorTCG.loja_jogador_link_id == link.id) &
            (LojaJogadorOrganizadorTCG.tcg == body.tcg)
        )
    ).first()

    if not organizador:
        raise TopDeckedException.bad_request(
            f"Jogador não é organizador de {body.tcg}"
        )

    session.delete(organizador)
    session.commit()

    return organizador

@router.post("/upload_banner", response_model=LojaPublico)
def update_banner(session: SessionDep,
                  token_data: Annotated[TokenData, Depends(retornar_loja_atual)],
                  file: UploadFile = File(None)):

    loja = session.get(Loja, token_data.id)

    if not loja:
        raise TopDeckedException.not_found("Loja nao encontrado")

    BASE_DIR = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    if file:
        ext = file.filename.split(".")[-1]
        file_path = os.path.join(
            UPLOAD_DIR, f"user_{loja.usuario.id}_banner.{ext}")
        with open(file_path, "wb") as f:
            f.write(file.file.read())
        loja.banner = f"user_{loja.usuario.id}_banner.{ext}"
        session.add(loja.usuario)
        session.commit()
    return loja
