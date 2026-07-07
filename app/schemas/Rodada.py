from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class RodadaPublico(BaseModel):
    id: int
    jogador1_id: Optional[int] = None
    jogador2_id: Optional[int] = None
    vencedor_id: Optional[int] = None
    num_rodada: int
    mesa: Optional[int] = None
    data_de_inicio: Optional[datetime] = None
    finalizada: Optional[bool] = False


class RodadaResultadoDTO(BaseModel):
    id_rodada: int
    id_vencedor: Optional[int] = None


class RodadaEditarDTO(BaseModel):
    """Edição livre de uma rodada/mesa pela aba "Rodadas" — diferente de
    RodadaResultadoDTO (usado por PUT rodadas/finalizar, uma ação em lote de
    "finalizar" que trava a rodada), aqui qualquer campo pode ser reeditado
    quantas vezes o organizador quiser. Todos os campos são opcionais —
    `exclude_unset=True` na rota decide o que de fato foi enviado."""
    jogador1_id: Optional[int] = None
    jogador2_id: Optional[int] = None
    vencedor_id: Optional[int] = None
