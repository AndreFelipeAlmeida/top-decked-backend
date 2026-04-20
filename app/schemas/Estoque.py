from typing import Optional
from pydantic import BaseModel
from app.utils.Enums import TipoMovimentacaoItem


class MovimentacaoItem(BaseModel):
    quantidade: int
    tipo: TipoMovimentacaoItem
    descricao: Optional[str] = None
