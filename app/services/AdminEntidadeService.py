"""CRUD dinâmico do painel do Administrador: metadados de cada tabela
(nome, tipo, obrigatoriedade, chave estrangeira) extraídos direto de
`__table__.columns`, em vez de uma rota/tela hardcoded por entidade.

ALLOWLIST curada, não reflection sobre toda `SQLModel.metadata.tables`:
`Usuario` (guarda hash de senha) e `Administrador` (evitar
auto-escalonamento de privilégio) ficam de fora de propósito. Tabelas
transacionais/log (JogadorTorneioLink, Rodada, HistoricoCredito etc.)
também ficam fora por ora — têm semântica de cascata própria que um DELETE
genérico via UI poderia violar sem querer.
"""

from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, Float, Integer
from sqlalchemy.sql.schema import Column
from sqlmodel import SQLModel, select

from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.models import (
    Categoria,
    Conquista,
    ConquistaNivel,
    Evento,
    Item,
    Jogador,
    JogadorCriado,
    Loja,
    MetaEvento,
    RegraPontuacaoEvento,
    RegraPontuacaoManualEvento,
    Temporada,
    TipoJogador,
    Torneio,
)

_MODELOS_GERENCIAVEIS: list[type[SQLModel]] = [
    Loja,
    Jogador,
    JogadorCriado,
    Torneio,
    TipoJogador,
    Temporada,
    Categoria,
    Item,
    Evento,
    MetaEvento,
    RegraPontuacaoEvento,
    RegraPontuacaoManualEvento,
    Conquista,
    ConquistaNivel,
]

# Chave = nome real da tabela no banco (model.__tablename__), não um slug
# inventado — isso deixa a resolução de FK automática, já que
# `coluna.foreign_keys` também aponta pro nome real da tabela alvo.
ENTIDADES_GERENCIAVEIS: dict[str, type[SQLModel]] = {
    model.__tablename__: model for model in _MODELOS_GERENCIAVEIS
}

_LABELS: dict[str, str] = {
    "loja": "Lojas",
    "jogador": "Jogadores",
    "jogadorcriado": "Jogadores Criados (por TCG)",
    "torneio": "Torneios",
    "tipojogador": "Regras de Pontuação (TipoJogador)",
    "temporada": "Temporadas",
    "categoria": "Categorias de Estoque",
    "item": "Itens de Estoque",
    "evento": "Eventos",
    "metaevento": "Metas de Evento",
    "regrapontuacaoevento": "Regras de Pontuação de Evento",
    "regrapontuacaomanualevento": "Regras de Pontuação Manual de Evento",
    "conquista": "Conquistas",
    "conquistanivel": "Níveis de Conquista",
}

_CAMPOS_OCULTOS = {"senha"}


def _buscar_model(nome: str) -> type[SQLModel]:
    model = ENTIDADES_GERENCIAVEIS.get(nome)
    if not model:
        raise TopDeckedException.not_found(f"Entidade '{nome}' não encontrada ou não gerenciável.")
    return model


def _coagir_id(model: type[SQLModel], registro_id: str) -> Any:
    """O id chega como string (parâmetro de URL) — a maioria das PKs é
    inteira (precisa virar int antes de `session.get`, senão o Postgres
    rejeita comparar uma coluna integer com um parâmetro texto), mas
    `Torneio.id` é uma string (UUID) de propósito, então fica como está."""
    coluna_pk = next(c for c in model.__table__.columns if c.primary_key)
    if isinstance(coluna_pk.type, Integer):
        try:
            return int(registro_id)
        except ValueError:
            raise TopDeckedException.bad_request(f"Id inválido: '{registro_id}'.")
    return registro_id


def _tipo_coluna(coluna: Column) -> str:
    tipo = coluna.type
    if isinstance(tipo, SAEnum):
        return "enum"
    if isinstance(tipo, Boolean):
        return "boolean"
    if isinstance(tipo, DateTime):
        return "datetime"
    if isinstance(tipo, Date):
        return "date"
    if isinstance(tipo, Integer):
        return "integer"
    if isinstance(tipo, Float):
        return "float"
    return "string"


def _serializar(registro: SQLModel) -> dict[str, Any]:
    return {campo: valor for campo, valor in registro.model_dump().items() if campo not in _CAMPOS_OCULTOS}


def listar_entidades() -> list[dict[str, str]]:
    return [
        {"nome": nome, "label": _LABELS.get(nome, model.__name__)}
        for nome, model in ENTIDADES_GERENCIAVEIS.items()
    ]


def descrever_colunas(nome: str) -> list[dict[str, Any]]:
    model = _buscar_model(nome)
    colunas = []
    for coluna in model.__table__.columns:
        if coluna.name in _CAMPOS_OCULTOS:
            continue
        tipo = _tipo_coluna(coluna)
        fk = next(iter(coluna.foreign_keys), None)
        colunas.append({
            "nome": coluna.name,
            "tipo": tipo,
            "nullable": coluna.nullable,
            "chave_primaria": coluna.primary_key,
            "enum_valores": list(coluna.type.enums) if tipo == "enum" else None,
            "chave_estrangeira": (
                {"tabela": fk.column.table.name, "coluna": fk.column.name} if fk else None
            ),
        })
    return colunas


def listar_registros(session: SessionDep, nome: str) -> list[dict[str, Any]]:
    model = _buscar_model(nome)
    registros = session.exec(select(model)).all()
    return [_serializar(registro) for registro in registros]


def _validar_e_filtrar_dados(session: SessionDep, model: type[SQLModel], dados: dict[str, Any]) -> dict[str, Any]:
    """Aceita só campos que de fato existem na tabela, nunca deixa
    sobrescrever a chave primária, e valida integridade referencial: todo
    valor de FK precisa apontar pra uma linha que realmente existe na
    tabela referenciada."""
    colunas = {coluna.name: coluna for coluna in model.__table__.columns}
    resultado: dict[str, Any] = {}

    for campo, valor in dados.items():
        if campo in _CAMPOS_OCULTOS:
            continue
        coluna = colunas.get(campo)
        if coluna is None or coluna.primary_key:
            continue

        fk = next(iter(coluna.foreign_keys), None)
        if fk is not None and valor is not None:
            tabela_alvo = fk.column.table
            existe = session.execute(
                select(1).select_from(tabela_alvo).where(fk.column == valor)
            ).first()
            if not existe:
                raise TopDeckedException.bad_request(
                    f"Valor inválido para '{campo}': não existe registro com "
                    f"id={valor} em '{tabela_alvo.name}'."
                )

        resultado[campo] = valor

    return resultado


def criar_registro(session: SessionDep, nome: str, dados: dict[str, Any]) -> dict[str, Any]:
    model = _buscar_model(nome)
    dados_validos = _validar_e_filtrar_dados(session, model, dados)
    registro = model(**dados_validos)
    session.add(registro)
    session.commit()
    session.refresh(registro)
    return _serializar(registro)


def atualizar_registro(session: SessionDep, nome: str, registro_id: str, dados: dict[str, Any]) -> dict[str, Any]:
    model = _buscar_model(nome)
    registro = session.get(model, _coagir_id(model, registro_id))
    if not registro:
        raise TopDeckedException.not_found(f"Registro '{registro_id}' não encontrado em '{nome}'.")

    dados_validos = _validar_e_filtrar_dados(session, model, dados)
    registro.sqlmodel_update(dados_validos)
    session.add(registro)
    session.commit()
    session.refresh(registro)
    return _serializar(registro)


def deletar_registro(session: SessionDep, nome: str, registro_id: str) -> None:
    model = _buscar_model(nome)
    registro = session.get(model, _coagir_id(model, registro_id))
    if not registro:
        raise TopDeckedException.not_found(f"Registro '{registro_id}' não encontrado em '{nome}'.")
    session.delete(registro)
    session.commit()
