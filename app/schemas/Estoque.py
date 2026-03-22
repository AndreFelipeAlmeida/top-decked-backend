from typing import Optional
from pydantic import BaseModel
from app.utils.Enums import TipoMovimentacaoEstoque


class MovimentacaoEstoque(BaseModel):
    quantidade: int
    tipo: TipoMovimentacaoEstoque
    descricao: Optional[str] = None
