from datetime import datetime, date
from zoneinfo import ZoneInfo
from app.core.exception import TopDeckedException

def data_agora_brasil():
    return datetime.now(ZoneInfo("America/Fortaleza")).date()

def agora_brasil():
    return datetime.now(ZoneInfo("America/Fortaleza"))


def parse_data(data_inicio_str: str) -> date:
    brasil_tz = ZoneInfo("America/Fortaleza")

    try:
        data = datetime.strptime(data_inicio_str, "%m/%d/%Y")
    except (ValueError, TypeError):
        # TypeError acontece quando data_inicio_str é None (tag/atributo
        # ausente no arquivo importado) — strptime só aceita string, e sem
        # esse catch a importação quebrava com um 500 sem mensagem nenhuma
        # em vez de um erro amigável (ver docs/IMPORTACAO.md).
        raise TopDeckedException.bad_request(
            "Data de início em formato inválido ou ausente")

    data = datetime(data.year, data.month, data.day, tzinfo=brasil_tz)
    return data.date()


def parse_datetime(datetime_inicio_str: str) -> datetime:
    brasil_tz = ZoneInfo("America/Fortaleza")

    try:
        data_hora = datetime.strptime(datetime_inicio_str, "%m/%d/%Y %H:%M:%S")
        data_hora = data_hora.replace(tzinfo=brasil_tz)
    except (ValueError, TypeError):
        # Idem parse_data: TypeError quando o valor vem None (ausente no
        # arquivo importado).
        raise TopDeckedException.bad_request(
            "Data/hora em formato inválido ou ausente")

    return data_hora
