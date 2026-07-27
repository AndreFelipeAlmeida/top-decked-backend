from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from app.core.db import SessionDep
from app.core.security import TokenData
from app.dependencies import retornar_loja_atual
from app.models import (
    HistoricoCredito,
    HistoricoItem,
    Item,
    ItemTransacao,
    LojaJogadorLink,
    Transacao,
)
from app.schemas.Pdv import VendaCreate, VendaResultado
from app.utils.Enums import TipoMovimentacaoCredito, TipoMovimentacaoItem

router = APIRouter(prefix="/lojas/pdv", tags=["PDV"])


@router.post("/checkout", response_model=VendaResultado)
def checkout(
    session: SessionDep,
    dados: VendaCreate,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)],
):
    if not dados.itens:
        raise HTTPException(status_code=400, detail="O carrinho está vazio.")

    itens_para_vender: list[tuple[Item, int]] = []
    total = 0.0

    for item_venda in dados.itens:
        if item_venda.quantidade <= 0:
            raise HTTPException(
                status_code=400, detail="Quantidade deve ser maior que zero.")

        item = session.exec(select(Item).where(
            Item.id == item_venda.item_id,
            Item.loja_id == loja.id,
        )).first()
        if not item:
            raise HTTPException(
                status_code=404, detail=f"Item {item_venda.item_id} não encontrado.")
        if not item.is_vendavel:
            raise HTTPException(
                status_code=400, detail=f"Item '{item.nome}' não está disponível para venda.")
        if item.quantidade < item_venda.quantidade:
            raise HTTPException(
                status_code=400, detail=f"Estoque insuficiente para '{item.nome}'.")

        itens_para_vender.append((item, item_venda.quantidade))
        total += item.preco * item_venda.quantidade

    credito_link = None
    if dados.abater_creditos:
        if not dados.jogador_id:
            raise HTTPException(
                status_code=400, detail="Selecione um jogador para abater créditos.")

        credito_link = session.exec(select(LojaJogadorLink).where(
            LojaJogadorLink.jogador_id == dados.jogador_id,
            LojaJogadorLink.loja_id == loja.id,
        )).first()
        if not credito_link:
            raise HTTPException(
                status_code=404, detail="Jogador não possui vínculo de créditos nesta loja.")

    credito_utilizado = min(credito_link.creditos, total) if credito_link else 0.0
    valor_pago_dinheiro = total - credito_utilizado

    transacao = Transacao(jogador_id=dados.jogador_id, loja_id=loja.id)
    session.add(transacao)
    session.flush()

    for item, quantidade in itens_para_vender:
        item.quantidade -= quantidade
        session.add(item)
        session.add(ItemTransacao(
            transacao_id=transacao.id,
            item_id=item.id,
            quantidade=quantidade,
            nome_item=item.nome,
            preco_unitario=item.preco,
        ))
        session.add(HistoricoItem(
            item_id=item.id,
            loja_id=loja.id,
            quantidade=quantidade,
            tipo=TipoMovimentacaoItem.VENDA,
            transacao_id=transacao.id,
            descricao=f"Venda de '{item.nome}'",
        ))

    if credito_link and credito_utilizado > 0:
        valor_antigo = credito_link.creditos
        credito_link.creditos = valor_antigo - credito_utilizado
        session.add(credito_link)
        session.add(HistoricoCredito(
            jogador_id=dados.jogador_id,
            loja_id=loja.id,
            valor_antigo=valor_antigo,
            valor_novo=credito_link.creditos,
            tipo=TipoMovimentacaoCredito.COMPRA,
            transacao_id=transacao.id,
            descricao="Abatimento de créditos em venda no PDV",
        ))

    session.commit()

    return VendaResultado(
        transacao_id=transacao.id,
        total=total,
        credito_utilizado=credito_utilizado,
        saldo_credito_restante=credito_link.creditos if credito_link else 0.0,
        valor_pago_dinheiro=valor_pago_dinheiro,
    )
