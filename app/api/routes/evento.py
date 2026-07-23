from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.dependencies import retornar_loja_atual, retornar_jogador_atual, retornar_usuario_atual, permitir_leitura_publica
from app.models import Evento, LojaJogadorLink, LojaJogadorOrganizadorTCG, MetaEvento, RegraPontuacaoEvento, RegraPontuacaoManualEvento
from app.schemas.Evento import (
    EventoAtualizarDTO,
    EventoCompletoPublico,
    EventoCriarDTO,
    EventoCriarOrganizadorDTO,
    EventoPublico,
    MetaEventoCriarDTO,
    MetaEventoPublico,
    ParticipanteEventoAdicionarDTO,
    ParticipanteEventoPublico,
    PontosManualEventoCriarDTO,
    RegraPontuacaoEventoCriarDTO,
    RegraPontuacaoEventoPublico,
    RegraPontuacaoManualEventoCriarDTO,
    RegraPontuacaoManualEventoPublico,
)
from app.schemas.JogadorCriado import JogadorCriadoPublico
from app.services.EventoService import (
    adicionar_participante,
    listar_jogadores_disponiveis,
    retornar_evento_completo,
    retornar_participante_completo,
    verificar_permissao_evento,
)
from app.models import ParticipanteEvento, PontosManualEvento

router = APIRouter(
    prefix="/lojas/eventos",
    tags=["Eventos"])


def _buscar_evento_ou_404(session: SessionDep, evento_id: int) -> Evento:
    evento = session.get(Evento, evento_id)
    if not evento:
        raise TopDeckedException.not_found("Evento não encontrado")
    return evento


@router.post("/", response_model=EventoPublico)
def criar_evento(session: SessionDep, evento: EventoCriarDTO, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    novo_evento = Evento(**evento.model_dump(), loja_id=loja.id)
    session.add(novo_evento)
    session.commit()
    session.refresh(novo_evento)
    return retornar_evento_completo(session, novo_evento)


@router.post("/organizador", response_model=EventoPublico)
def criar_evento_organizador(
    session: SessionDep,
    evento: EventoCriarOrganizadorDTO,
    jogador: Annotated[TokenData, Depends(retornar_jogador_atual)],
):
    link = session.exec(
        select(LojaJogadorLink).where(
            (LojaJogadorLink.loja_id == evento.loja_id) & (LojaJogadorLink.jogador_id == jogador.id)
        )
    ).first()
    if not link:
        raise TopDeckedException.forbidden("Jogador não pertence a esta loja")

    organiza_tcg = session.exec(
        select(LojaJogadorOrganizadorTCG).where(
            (LojaJogadorOrganizadorTCG.loja_jogador_link_id == link.id) &
            (LojaJogadorOrganizadorTCG.tcg == evento.tcg)
        )
    ).first()
    if not organiza_tcg:
        raise TopDeckedException.forbidden(
            "Jogador não possui permissão para criar eventos deste TCG nesta loja")

    dados = evento.model_dump(exclude={"loja_id"})
    novo_evento = Evento(**dados, loja_id=evento.loja_id)
    session.add(novo_evento)
    session.commit()
    session.refresh(novo_evento)
    return retornar_evento_completo(session, novo_evento)


@router.get("/", response_model=list[EventoPublico])
def get_eventos(
    session: SessionDep,
    _: Annotated[TokenData, Depends(retornar_usuario_atual)],
    _leitura_publica: Annotated[None, Depends(permitir_leitura_publica)],
    tcg: str | None = None,
):
    # Mesmo padrão de GET /lojas/torneios/ — jogadores navegam eventos de
    # qualquer loja (descoberta), não só os que já participam.
    # permitir_leitura_publica declara pro RLS que esta leitura é
    # deliberadamente cross-tenant (ver dependencies.py).
    query = select(Evento)
    if tcg:
        query = query.where(Evento.tcg == tcg)
    eventos = session.exec(query).all()
    return [retornar_evento_completo(session, evento) for evento in eventos]


@router.get("/loja", response_model=list[EventoPublico])
def get_eventos_da_loja(session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)], tcg: str | None = None):
    query = select(Evento).where(Evento.loja_id == loja.id)
    if tcg:
        query = query.where(Evento.tcg == tcg)
    eventos = session.exec(query).all()
    return [retornar_evento_completo(session, evento) for evento in eventos]


@router.get("/{evento_id}", response_model=EventoCompletoPublico)
def get_evento(
    session: SessionDep,
    evento_id: int,
    _: Annotated[TokenData, Depends(retornar_usuario_atual)],
    _leitura_publica: Annotated[None, Depends(permitir_leitura_publica)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    return retornar_evento_completo(session, evento)


@router.put("/{evento_id}", response_model=EventoPublico)
def atualizar_evento(
    session: SessionDep,
    evento_id: int,
    dados: EventoAtualizarDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    atualizacoes = dados.model_dump(exclude_unset=True)
    evento.sqlmodel_update(atualizacoes)
    session.add(evento)
    session.commit()
    session.refresh(evento)
    return retornar_evento_completo(session, evento)


@router.delete("/{evento_id}", status_code=204)
def deletar_evento(session: SessionDep, evento_id: int, usuario: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    session.delete(evento)
    session.commit()


@router.get("/{evento_id}/jogadores-disponiveis", response_model=list[JogadorCriadoPublico])
def get_jogadores_disponiveis_evento(
    session: SessionDep,
    evento_id: int,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)
    return listar_jogadores_disponiveis(session, evento)


@router.post("/{evento_id}/participantes", response_model=ParticipanteEventoPublico)
def criar_participante_evento(
    session: SessionDep,
    evento_id: int,
    dados: ParticipanteEventoAdicionarDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    participante = adicionar_participante(session, evento, dados.jogador_criado_id)
    return retornar_participante_completo(session, evento, participante)


@router.post("/{evento_id}/pontos-manuais", response_model=ParticipanteEventoPublico)
def criar_pontos_manuais_evento(
    session: SessionDep,
    evento_id: int,
    dados: PontosManualEventoCriarDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    participante = session.exec(
        select(ParticipanteEvento).where(
            (ParticipanteEvento.evento_id == evento_id) &
            (ParticipanteEvento.jogador_criado_id == dados.jogador_criado_id)
        )
    ).first()
    if not participante:
        raise TopDeckedException.not_found("Esse jogador não é participante deste evento")

    pontos_manuais = PontosManualEvento(
        evento_id=evento_id,
        jogador_criado_id=dados.jogador_criado_id,
        descricao=dados.descricao,
        pontos=dados.pontos,
    )
    session.add(pontos_manuais)
    session.commit()
    session.refresh(participante)

    return retornar_participante_completo(session, evento, participante)


@router.post("/{evento_id}/metas", response_model=MetaEventoPublico)
def criar_meta_evento(
    session: SessionDep,
    evento_id: int,
    dados: MetaEventoCriarDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    meta = MetaEvento(**dados.model_dump(), evento_id=evento_id)
    session.add(meta)
    session.commit()
    session.refresh(meta)
    return meta


@router.put("/{evento_id}/metas/{meta_id}", response_model=MetaEventoPublico)
def atualizar_meta_evento(
    session: SessionDep,
    evento_id: int,
    meta_id: int,
    dados: MetaEventoCriarDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    meta = session.get(MetaEvento, meta_id)
    if not meta or meta.evento_id != evento_id:
        raise TopDeckedException.not_found("Meta não encontrada neste evento")

    meta.sqlmodel_update(dados.model_dump())
    session.add(meta)
    session.commit()
    session.refresh(meta)
    return meta


@router.delete("/{evento_id}/metas/{meta_id}", status_code=204)
def deletar_meta_evento(
    session: SessionDep,
    evento_id: int,
    meta_id: int,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    meta = session.get(MetaEvento, meta_id)
    if not meta or meta.evento_id != evento_id:
        raise TopDeckedException.not_found("Meta não encontrada neste evento")

    session.delete(meta)
    session.commit()


@router.post("/{evento_id}/regras", response_model=RegraPontuacaoEventoPublico)
def criar_regra_evento(
    session: SessionDep,
    evento_id: int,
    dados: RegraPontuacaoEventoCriarDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    regra = RegraPontuacaoEvento(**dados.model_dump(), evento_id=evento_id)
    session.add(regra)
    session.commit()
    session.refresh(regra)
    return regra


@router.put("/{evento_id}/regras/{regra_id}", response_model=RegraPontuacaoEventoPublico)
def atualizar_regra_evento(
    session: SessionDep,
    evento_id: int,
    regra_id: int,
    dados: RegraPontuacaoEventoCriarDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    regra = session.get(RegraPontuacaoEvento, regra_id)
    if not regra or regra.evento_id != evento_id:
        raise TopDeckedException.not_found("Regra não encontrada neste evento")

    regra.sqlmodel_update(dados.model_dump())
    session.add(regra)
    session.commit()
    session.refresh(regra)
    return regra


@router.delete("/{evento_id}/regras/{regra_id}", status_code=204)
def deletar_regra_evento(
    session: SessionDep,
    evento_id: int,
    regra_id: int,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    regra = session.get(RegraPontuacaoEvento, regra_id)
    if not regra or regra.evento_id != evento_id:
        raise TopDeckedException.not_found("Regra não encontrada neste evento")

    session.delete(regra)
    session.commit()


@router.post("/{evento_id}/regras-manuais", response_model=RegraPontuacaoManualEventoPublico)
def criar_regra_manual_evento(
    session: SessionDep,
    evento_id: int,
    dados: RegraPontuacaoManualEventoCriarDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    regra = RegraPontuacaoManualEvento(**dados.model_dump(), evento_id=evento_id)
    session.add(regra)
    session.commit()
    session.refresh(regra)
    return regra


@router.put("/{evento_id}/regras-manuais/{regra_id}", response_model=RegraPontuacaoManualEventoPublico)
def atualizar_regra_manual_evento(
    session: SessionDep,
    evento_id: int,
    regra_id: int,
    dados: RegraPontuacaoManualEventoCriarDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    regra = session.get(RegraPontuacaoManualEvento, regra_id)
    if not regra or regra.evento_id != evento_id:
        raise TopDeckedException.not_found("Regra manual não encontrada neste evento")

    regra.sqlmodel_update(dados.model_dump())
    session.add(regra)
    session.commit()
    session.refresh(regra)
    return regra


@router.delete("/{evento_id}/regras-manuais/{regra_id}", status_code=204)
def deletar_regra_manual_evento(
    session: SessionDep,
    evento_id: int,
    regra_id: int,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    evento = _buscar_evento_ou_404(session, evento_id)
    verificar_permissao_evento(session, evento, usuario)

    regra = session.get(RegraPontuacaoManualEvento, regra_id)
    if not regra or regra.evento_id != evento_id:
        raise TopDeckedException.not_found("Regra manual não encontrada neste evento")

    session.delete(regra)
    session.commit()
