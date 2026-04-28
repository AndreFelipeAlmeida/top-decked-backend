from typing import Optional
from pydantic import BaseModel
from enum import Enum


class TipoMovimentacaoItemUpdate(str, Enum):
    ENTRADA = "entrada"
    SAIDA = "saida"


class MovimentacaoItem(BaseModel):
    quantidade: int
    tipo: TipoMovimentacaoItemUpdate
    descricao: Optional[str] = None
