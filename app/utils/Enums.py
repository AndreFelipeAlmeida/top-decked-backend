from enum import Enum


class MesEnum(str, Enum):
    Janeiro = "Jan"
    Fevereiro = "Fev"
    Marco = "Mar"
    Abril = "Abr"
    Maio = "Mai"
    Junho = "Jun"
    Julho = "Jul"
    Agosto = "Ago"
    Setembro = "Set"
    Outubro = "Out"
    Novembro = "Nov"
    Dezembro = "Dez"

    @classmethod
    def abreviacao(cls, mes: int) -> str:
        mes_map = {
            1: cls.Janeiro.value,
            2: cls.Fevereiro.value,
            3: cls.Marco.value,
            4: cls.Abril.value,
            5: cls.Maio.value,
            6: cls.Junho.value,
            7: cls.Julho.value,
            8: cls.Agosto.value,
            9: cls.Setembro.value,
            10: cls.Outubro.value,
            11: cls.Novembro.value,
            12: cls.Dezembro.value,
        }
        return mes_map.get(mes, "Desconhecido")


class StatusTorneio(str, Enum):
    ABERTO = "ABERTO"
    EM_ANDAMENTO = "EM_ANDAMENTO"
    FINALIZADO = "FINALIZADO"


class CategoriaItem(str, Enum):
    CANTINA = "CANTINA"
    GERAIS = "GERAIS"
