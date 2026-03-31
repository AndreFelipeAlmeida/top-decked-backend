from typing import Optional
from sqlmodel import SQLModel
from app.models import LojaJogadorLinkBase
from app.schemas.GameID import GameIDPublico
from app.schemas.Jogador import JogadorPublico


class CreditoCreate(SQLModel):
    apelido: str
    game_id: GameIDPublico


class CreditoUpdate(SQLModel):
    quantidade: float


class CreditoAdd(SQLModel):
    novos_creditos: float


class CreditoRemove(SQLModel):
    retirar_creditos: float


class CreditoJogador(LojaJogadorLinkBase):
    nome_loja: str
    endereco: str

class LojaJogadorPublico(LojaJogadorLinkBase):
    jogador: Optional["JogadorPublico"]