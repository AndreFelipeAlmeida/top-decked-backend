"""Cálculo de categoria de idade (Junior/Senior/Master) dentro de uma
Temporada Pokémon — ver docs/TEMPORADAS.md para a regra completa e o porquê.

Regra oficial de Pokémon Organized Play: a categoria de um jogador numa
temporada é definida pela idade que ele **completa até o último dia da
temporada** (não a idade que ele tem no início dela). Por isso alguém que
faz aniversário no meio da temporada já entra na categoria da idade nova
mesmo que a maior parte da temporada ainda não tenha acontecido quando ele
fez aniversário.
"""

import calendar
from datetime import date

from app.models import Temporada, Torneio
from app.core.db import SessionDep
from app.utils.TorneioDataUtil import data_efetiva_torneio
from sqlmodel import select

IDADE_MAXIMA_JUNIOR = 12
IDADE_MAXIMA_SENIOR = 16


def ultimo_dia_da_temporada(temporada: Temporada) -> date:
    ultimo_dia = calendar.monthrange(temporada.ano_fim, temporada.mes_fim)[1]
    return date(temporada.ano_fim, temporada.mes_fim, ultimo_dia)


def calcular_idade_na_data(data_nascimento: date, data_referencia: date) -> int:
    idade = data_referencia.year - data_nascimento.year
    aniversario_ja_passou_no_ano = (data_referencia.month, data_referencia.day) >= (
        data_nascimento.month,
        data_nascimento.day,
    )
    if not aniversario_ja_passou_no_ano:
        idade -= 1
    return idade


def calcular_categoria_por_idade(idade: int) -> str:
    if idade <= IDADE_MAXIMA_JUNIOR:
        return "Junior"
    if idade <= IDADE_MAXIMA_SENIOR:
        return "Senior"
    return "Master"


def calcular_categoria_na_temporada(data_nascimento: date, temporada: Temporada) -> str:
    idade = calcular_idade_na_data(data_nascimento, ultimo_dia_da_temporada(temporada))
    return calcular_categoria_por_idade(idade)


def encontrar_temporada_do_torneio(session: SessionDep, torneio: Torneio) -> Temporada | None:
    """A temporada de um torneio é decidida pela DATA dele, nunca escolhida
    manualmente: entre as temporadas cadastradas pra loja/jogo do torneio,
    procura uma cujo intervalo [início, fim] (em mês/ano) contenha a data
    efetiva do torneio (real, se já FINALIZADO — nunca mais a planejada
    depois disso; ver TorneioDataUtil.data_efetiva_torneio). Se nenhuma
    bater (ou a loja não cadastrou nenhuma temporada pro jogo ainda),
    retorna None — sem temporada não dá pra calcular categoria."""
    if torneio.data_planejada is None:
        return None

    data = data_efetiva_torneio(torneio)
    ano, mes = data.year, data.month

    temporadas = session.exec(
        select(Temporada).where(
            (Temporada.loja_id == torneio.loja_id) & (Temporada.tcg == torneio.jogo)
        )
    ).all()

    for temporada in temporadas:
        inicio = (temporada.ano_inicio, temporada.mes_inicio)
        fim = (temporada.ano_fim, temporada.mes_fim)
        if inicio <= (ano, mes) <= fim:
            return temporada

    return None
