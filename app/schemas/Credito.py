from sqlmodel import SQLModel
from app.models import Credito


class CreditoCreate(SQLModel):
    jogador_id: int
    quantidade: float


class CreditoUpdate(SQLModel):
    quantidade: float


class CreditoAdd(SQLModel):
    novos_creditos: float


class CreditoRemove(SQLModel):
    retirar_creditos: float


class CreditoJogador(Credito):
    nome_loja: str
    endereco: str
