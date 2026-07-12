from pydantic import field_validator
from app.models import TemporadaBase


def _validar_mes(mes: int) -> int:
    if not 1 <= mes <= 12:
        raise ValueError("Mês precisa estar entre 1 e 12")
    return mes


class TemporadaCriarDTO(TemporadaBase):
    @field_validator("mes_inicio", "mes_fim")
    @classmethod
    def validar_mes(cls, v: int) -> int:
        return _validar_mes(v)

    @field_validator("mes_fim")
    @classmethod
    def validar_intervalo(cls, mes_fim: int, info) -> int:
        ano_inicio = info.data.get("ano_inicio")
        mes_inicio = info.data.get("mes_inicio")
        ano_fim = info.data.get("ano_fim")
        if ano_inicio is None or mes_inicio is None or ano_fim is None:
            return mes_fim
        if (ano_fim, mes_fim) < (ano_inicio, mes_inicio):
            raise ValueError("O fim da temporada não pode ser antes do início")
        return mes_fim


class TemporadaCriarOrganizadorDTO(TemporadaCriarDTO):
    loja_id: int


class TemporadaPublico(TemporadaBase):
    id: int
    loja_id: int
