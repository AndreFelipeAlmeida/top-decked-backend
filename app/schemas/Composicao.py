from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.utils.Enums import TCG


class UnidadeCatalogoPublico(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tcg: TCG
    external_id: int
    nome: str


class RepresentacaoComposicaoCriarDTO(BaseModel):
    tcg: TCG
    nome: Optional[str] = None
    unidade_1_id: int
    unidade_2_id: int

    @field_validator("nome")
    @classmethod
    def vazio_vira_none(cls, valor):
        return valor or None


class RepresentacaoComposicaoPublico(BaseModel):
    id: int
    tcg: TCG
    nome: str
    unidades: list[UnidadeCatalogoPublico]


class ComposicaoUnidadeDTO(BaseModel):
    unidade_catalogo_id: int
    quantidade: int = Field(gt=0)


class ComposicaoUnidadePublico(BaseModel):
    unidade_catalogo_id: int
    unidade: UnidadeCatalogoPublico
    quantidade: int


class JogadorComposicaoDTO(BaseModel):
    composicao_representacao_id: Optional[int] = None
    composicao_unidades: list[ComposicaoUnidadeDTO] = Field(default_factory=list)


class ComposicaoPartidaPublico(BaseModel):
    id: int
    unidades: list[ComposicaoUnidadePublico]


class ComposicaoPartidaAtualizarDTO(BaseModel):
    unidades: list[ComposicaoUnidadeDTO] = Field(default_factory=list)
