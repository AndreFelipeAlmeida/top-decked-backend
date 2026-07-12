from enum import Enum


class TCG(str, Enum):
    # Mantido em sincronia com as opções da sidebar do frontend
    # (`src/lib/tcgGames.ts`) — ver `docs/DIVIDA_TECNICA.md` item 42. Antes
    # tinha YUGIOH/MAGIC (nunca ofertados na sidebar) e não tinha ONEPIECE/
    # POKEMON_GO (ofertados desabilitados na sidebar, mas inexistentes aqui).
    POKEMON = "POKEMON"
    ONEPIECE = "ONEPIECE"
    # Não é um TCG (jogo de cartas colecionáveis) de verdade — é o formato
    # competitivo de video game da Pokémon Company — mas convive no mesmo
    # enum porque `Torneio.jogo` (ver models.py) representa "qual jogo este
    # torneio é", não estritamente "qual TCG".
    POKEMON_VGC = "POKEMON_VGC"
    POKEMON_GO = "POKEMON_GO"

    @property
    def label(self):
        return {
            "POKEMON": "Pokémon",
            "ONEPIECE": "One Piece TCG",
            "POKEMON_VGC": "Pokémon VGC",
            "POKEMON_GO": "Pokémon GO",
        }[self.value]


class FormatoTorneio(str, Enum):
    # Só Pokémon TCG está implementado ponta a ponta hoje (ver
    # `docs/COMPOSICAO.md`/`docs/RANKING.md`), então os formatos abaixo são
    # os de Pokémon TCG — não Magic/outro TCG (ver `docs/DIVIDA_TECNICA.md`
    # item 43). Lista deliberadamente curta ("por enquanto"); crescer aqui
    # não exige migração.
    PADRAO = "PADRAO"
    GLC = "GLC"
    DRAFT = "DRAFT"

    @property
    def label(self):
        return {
            "PADRAO": "Padrão",
            "GLC": "GLC",
            "DRAFT": "Draft",
        }[self.value]


class FormatoMD(str, Enum):
    # "Melhor de X" (best-of-X) — informativo apenas: registra qual formato
    # de partida o torneio usa (MD1/MD3/MD5), mas o sistema não modela
    # partidas individuais dentro de uma rodada (ver docs/PARTIDAS.md) — cada
    # rodada segue sendo uma mesa só, com um único vencedor.
    MD1 = "MD1"
    MD3 = "MD3"
    MD5 = "MD5"

    @property
    def label(self):
        return {
            "MD1": "Melhor de 1",
            "MD3": "Melhor de 3",
            "MD5": "Melhor de 5",
        }[self.value]


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


# Toda Loja nasce PENDENTE — mesmo já com e-mail confirmado
# (Usuario.is_active) — e só pode autenticar depois de um Administrador
# aprovar o cadastro.
class StatusAprovacaoLoja(str, Enum):
    PENDENTE = "PENDENTE"
    APROVADA = "APROVADA"
    REJEITADA = "REJEITADA"


class TipoTorneio(str, Enum):
    IMPORTADO = "IMPORTADO"
    CRIADO = "CRIADO"


class TipoParticipanteTorneio(str, Enum):
    # Papel do jogador DENTRO de um torneio específico (JogadorTorneioLink.tipo)
    # — não confundir com a conta em si (Jogador/JogadorCriado), que não tem
    # papel nenhum, só participações. Um JUIZ ganha pontuação extra normalmente
    # (ver docs/PONTUACAO_EXTRA.md) mas não entra no pareamento de rodadas nem
    # no ranking/pódio DESSE torneio — só no ranking geral entre torneios.
    # Um jogador só tem UMA linha de JogadorTorneioLink por torneio (fonte
    # única de verdade); JOGADOR_E_JUIZ é o valor usado quando ele acumula
    # os dois papéis nesse torneio, em vez de duas linhas separadas.
    JOGADOR = "JOGADOR"
    JUIZ = "JUIZ"
    JOGADOR_E_JUIZ = "JOGADOR_E_JUIZ"


class MotivoPontuacaoExtra(str, Enum):
    NOVATO = "NOVATO"   # "Trouxe um Novato"
    JUIZ = "JUIZ"
    OUTROS = "OUTROS"


class TipoRegraPontuacaoEvento(str, Enum):
    # Gatilho automático que uma regra de pontuação de Evento observa nos
    # torneios do período (ver docs/EVENTOS.md) — contabilizado a partir de
    # JogadorTorneioLink.vitorias/derrotas/empates (já calculados pelo
    # desempate suíço, ver docs/RANKING.md) e da simples presença do
    # jogador num torneio (participação).
    VITORIA = "VITORIA"
    DERROTA = "DERROTA"
    EMPATE = "EMPATE"
    PARTICIPACAO = "PARTICIPACAO"


class TipoMovimentacaoCredito(str, Enum):
    ADICAO = "adicao"
    REMOCAO = "remocao"
    COMPRA = "compra"
    CADASTRO = "cadastro"


class TipoMovimentacaoItem(str, Enum):
    ENTRADA = "entrada"
    SAIDA = "saida"
    VENDA = "venda"
    REPOSICAO = "reposicao"
    ALTERACAO = "alteracao"
    CADASTRO = "cadastro"
    REMOCAO = "remocao"


class CategoriaConquista(str, Enum):
    HORAS_JOGADAS = "HORAS_JOGADAS"
    TORNEIOS_JOGADOS = "TORNEIOS_JOGADOS"
    VITORIAS = "VITORIAS"
    COMPOSICOES_JOGADAS = "COMPOSICOES_JOGADAS"
    SEQUENCIA_VITORIAS = "SEQUENCIA_VITORIAS"
    PODIOS = "PODIOS"
    # extensível: uma nova categoria aqui + uma função de cálculo em
    # ConquistaService.py habilitam uma nova família de conquista, sem migração.
