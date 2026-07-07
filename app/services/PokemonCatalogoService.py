import re
from datetime import timedelta

import httpx
from sqlmodel import select

from app.core.db import SessionDep
from app.models import CatalogoAtualizacao, UnidadeCatalogo
from app.utils.Enums import TCG
from app.utils.datetimeUtil import agora_brasil

POKEAPI_URL = "https://pokeapi.co/api/v2/pokemon"
DIAS_PARA_REATUALIZAR = 30

# Pokémon TCG, Pokémon VGC e Pokémon GO compartilham o mesmo catálogo de
# espécies (a PokeAPI não distingue nenhum dos três) — cada um recebe suas
# próprias linhas em `UnidadeCatalogo`/`CatalogoAtualizacao` (mesmo
# external_id, tcg diferente), pra manter as rotas de /unidades e
# representações genéricas por `tcg` sem precisar de nenhum caso especial.
# Ver docs/COMPOSICAO.md.
JOGOS_CATALOGO_POKEMON = (TCG.POKEMON, TCG.POKEMON_VGC, TCG.POKEMON_GO)

# Local pra cadastrar Pokémon manualmente (formas/variantes que a PokeAPI não
# tenha, correções pontuais, ou entradas pra usar antes do próximo fetch
# mensal). external_id = número da pokedex a usar pra montar a sprite em
# https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{external_id}.png
ENTRADAS_MANUAIS_POKEMON: list[dict] = [
    # {"external_id": 10034, "nome": "pikachu-cosplay"},
]


def _extrair_id_da_url(url: str) -> int | None:
    # url vem como "https://pokeapi.co/api/v2/pokemon/887/"
    match = re.search(r"/pokemon/(\d+)/?$", url)
    return int(match.group(1)) if match else None


def buscar_pokemons_pokeapi() -> list[dict]:
    """Busca a lista completa de Pokémon na PokeAPI (nome + número da pokedex).
    Um request só resolve, já que passar um limit maior que o total (~1350
    hoje) traz tudo de uma vez — ver docs/COMPOSICAO.md seção 3."""
    with httpx.Client(timeout=30) as client:
        resposta = client.get(POKEAPI_URL, params={"limit": 2000, "offset": 0})
        resposta.raise_for_status()
        dados = resposta.json()

    pokemons = []
    for item in dados.get("results", []):
        external_id = _extrair_id_da_url(item["url"])
        if external_id is not None:
            pokemons.append({"external_id": external_id, "nome": item["name"]})

    return pokemons


def atualizar_catalogo_pokemon(session: SessionDep, tcg: TCG = TCG.POKEMON) -> int:
    """Busca a lista atual na PokeAPI e insere quem ainda não está no catálogo
    (upsert simples por external_id) **para o `tcg` passado** — TCG e VGC
    chamam essa função cada um com seu próprio valor, já que compartilham a
    mesma fonte de dados mas precisam de linhas próprias em `UnidadeCatalogo`
    (ver JOGOS_CATALOGO_POKEMON). Entradas manuais nunca são sobrescritas por
    aqui. Retorna quantas unidades novas foram inseridas."""
    pokemons = buscar_pokemons_pokeapi()

    existentes = {
        p.external_id
        for p in session.exec(
            select(UnidadeCatalogo).where(UnidadeCatalogo.tcg == tcg)
        ).all()
    }

    novos = 0
    for pokemon in pokemons:
        if pokemon["external_id"] in existentes:
            continue
        session.add(UnidadeCatalogo(
            tcg=tcg,
            external_id=pokemon["external_id"],
            nome=pokemon["nome"],
            manual=False,
        ))
        novos += 1

    for entrada in ENTRADAS_MANUAIS_POKEMON:
        if entrada["external_id"] in existentes:
            continue
        session.add(UnidadeCatalogo(
            tcg=tcg,
            external_id=entrada["external_id"],
            nome=entrada["nome"],
            manual=True,
        ))
        novos += 1

    controle = session.get(CatalogoAtualizacao, tcg)
    if controle:
        controle.atualizado_em = agora_brasil()
    else:
        controle = CatalogoAtualizacao(tcg=tcg, atualizado_em=agora_brasil())
    session.add(controle)

    session.commit()
    return novos


def garantir_catalogo_atualizado(session: SessionDep) -> None:
    """Chamado na subida da aplicação (ver app/main.py) — só bate na PokeAPI se
    o catálogo de um jogo nunca foi buscado ou já passou de
    DIAS_PARA_REATUALIZAR dias ("uma vez por mês" da spec, sem precisar de um
    scheduler dedicado). Roda uma vez por jogo em JOGOS_CATALOGO_POKEMON —
    cada um tem seu próprio controle de `CatalogoAtualizacao`, então um pode
    estar em dia enquanto o outro é rebuscado (ex.: VGC habilitado depois do
    TCG já estar populado)."""
    agora = agora_brasil()

    for tcg in JOGOS_CATALOGO_POKEMON:
        controle = session.get(CatalogoAtualizacao, tcg)

        if controle:
            atualizado_em = controle.atualizado_em
            # SQLite não preserva tzinfo mesmo com DateTime(timezone=True) — o
            # valor lido de volta vem "naive", mas representa o mesmo horário
            # de parede que foi gravado com agora_brasil(), então é seguro
            # reanexar o mesmo fuso pra poder subtrair.
            if atualizado_em.tzinfo is None:
                atualizado_em = atualizado_em.replace(tzinfo=agora.tzinfo)

            if agora - atualizado_em < timedelta(days=DIAS_PARA_REATUALIZAR):
                continue

        try:
            atualizar_catalogo_pokemon(session, tcg)
        except httpx.HTTPError:
            # PokeAPI fora do ar não deve derrubar a subida da aplicação — o
            # catálogo simplesmente fica com o que já tinha (ou vazio, na
            # primeira vez) até a próxima tentativa.
            pass
