from pydantic import BaseModel

class Ranking(BaseModel):
    jogador_id: str | None
    game_id: str | None
    nome_jogador: str
    pontos: float
    torneios: int
    vitorias: int
    derrotas: int
    empates: int
    taxa_vitoria: float

class RankingPorLoja(BaseModel):
    nome_jogador: str
    nome_loja: str
    pontos: float
    torneios: int
    vitorias: int
    derrotas: int
    empates: int
    taxa_vitoria: float

class RankingPorFormato(BaseModel):
    formato: str
    pontos: float
    vitorias: int
    taxa_vitoria: float