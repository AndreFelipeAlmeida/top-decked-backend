from typing import Optional
from pydantic import model_validator
from sqlmodel import SQLModel
from app.models import LojaJogadorLinkBase, LojaJogadorOrganizadorTCG
from app.schemas.GameID import GameIDPublico
from app.schemas.JogadorCriado import JogadorCriadoPublico
from app.schemas.Loja import LojaPublico
from app.utils.Enums import TCG

class CreditoCreate(SQLModel):
    apelido: str
    game_id: GameIDPublico


class CreditoUpdate(SQLModel):
    quantidade: float


class CreditoAdd(SQLModel):
    novos_creditos: float


class CreditoRemove(SQLModel):
    retirar_creditos: float


class _JogadorComTcgsPublico(SQLModel):
    nome: str
    tcgs: list[JogadorCriadoPublico] = []


class _ComGameIdDerivado(SQLModel):
    jogador: Optional[_JogadorComTcgsPublico] = None
    game_id: Optional[str] = None
    tcg: Optional[TCG] = None

    @model_validator(mode="after")
    def _preencher_game_id_tcg(self):
        if self.jogador and self.jogador.tcgs:
            primeiro = self.jogador.tcgs[0]
            self.game_id = primeiro.game_id
            self.tcg = primeiro.tcg
        return self


class CreditoJogador(LojaJogadorLinkBase, _ComGameIdDerivado):
    nome_loja: str
    endereco: str

class LojaJogadorPublico(LojaJogadorLinkBase, _ComGameIdDerivado):
    loja: LojaPublico
    organizacoes: list["LojaJogadorOrganizadorTCG"] = []

class PromoverOrganizadorDTO(SQLModel):
    tcg: TCG
