from sqlmodel import Session, text


def definir_tenant_sessao(session: Session, loja_id: int | None) -> None:
    """Define `app.current_loja_id` na sessão Postgres atual — é essa
    variável que as policies de RLS (BRK-306, ver
    migrations/versions/*_rls_tabelas_escopadas_por_loja.py) leem via
    `current_setting('app.current_loja_id', true)`.

    `SET LOCAL` só vale dentro da transação corrente e é revertido no
    commit/rollback — não vaza pra próxima requisição que reusar a mesma
    conexão do pool.

    Ainda não é chamada em lugar nenhum do request lifecycle — quem
    resolve "qual loja está autenticada" hoje são as dependencies em
    app/dependencies.py (retornar_loja_atual etc.), então plugar esta
    função nelas é o próximo passo natural (fora do escopo desta sprint,
    que só estabelece a fundação de banco). Em SQLite (dev/teste) esta
    função é um no-op silencioso — `current_setting` nem existe lá, e a
    aplicação já garante isolamento por loja nos services.
    """
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return

    valor = "NULL" if loja_id is None else str(int(loja_id))
    session.exec(text(f"SET LOCAL app.current_loja_id = {valor}"))
