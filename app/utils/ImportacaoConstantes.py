from enum import IntEnum


class CategoriaOficialTDF(IntEnum):
    """Código de categoria de idade usado na seção <standings> de um
    arquivo de torneio exportado — <pod category="0|1|2" type="...">."""
    JUNIOR = 0
    SENIOR = 1
    MASTER = 2


TIPO_POD_FINALIZADO = "finished"
TIPO_POD_DNF = "dnf"
