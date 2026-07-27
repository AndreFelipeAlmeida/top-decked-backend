from pydantic import BaseModel


class ItemVendaCreate(BaseModel):
    item_id: int
    quantidade: int


class VendaCreate(BaseModel):
    jogador_id: int | None = None
    itens: list[ItemVendaCreate]
    abater_creditos: bool = False


class VendaResultado(BaseModel):
    transacao_id: int
    total: float
    credito_utilizado: float
    saldo_credito_restante: float
    valor_pago_dinheiro: float
