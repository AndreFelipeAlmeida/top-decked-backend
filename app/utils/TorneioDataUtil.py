from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.models import Torneio
from app.utils.Enums import StatusTorneio

BRASIL_TZ = ZoneInfo("America/Fortaleza")


def momento_efetivo_torneio(torneio: Torneio) -> datetime:
    """O instante "de verdade" de um torneio pra qualquer regra de negócio
    (temporada, período de evento, ordem cronológica de pontos): enquanto
    ele não termina, só existe a data/hora planejada (o que vai acontecer);
    depois de FINALIZADO, o que de fato aconteceu (inicio_real) é que vale
    — nunca mais a planejada, que pode ter sido só uma estimativa inicial."""
    if torneio.status == StatusTorneio.FINALIZADO and torneio.inicio_real:
        return torneio.inicio_real
    hora = torneio.hora_planejada or time.min
    return datetime.combine(torneio.data_planejada, hora, tzinfo=BRASIL_TZ)


def data_efetiva_torneio(torneio: Torneio) -> date:
    """Só o dia do momento efetivo, normalizado pro fuso horário de negócio
    (Brasil) antes de truncar a hora — comparar/agrupar por data sem essa
    normalização é o clássico bug de perder um dia perto da virada de mês
    em fusos negativos."""
    return momento_efetivo_torneio(torneio).astimezone(BRASIL_TZ).date()
