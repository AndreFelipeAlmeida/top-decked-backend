from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.models import ConquistaBase
from app.utils.Enums import CategoriaConquista


class ConquistaNivelPublico(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nivel: int
    nome_nivel: str
    meta: float


class ConquistaPublico(ConquistaBase):
    id: int
    niveis: list[ConquistaNivelPublico]


class JogadorConquistaPublico(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conquista: ConquistaPublico
    progresso_atual: float
    nivel_atual: int
    nivel_atual_em: Optional[datetime]


class HistoricoConquistaPublico(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conquista_codigo: str
    conquista_nome: str
    conquista_icone: str
    categoria: CategoriaConquista
    nivel: int
    nome_nivel: str
    conquistado_em: datetime
