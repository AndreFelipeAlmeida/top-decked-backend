from sqlmodel import Session, text


def definir_tenant_sessao(session: Session, loja_id: int | None) -> None:
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return

    valor = "NULL" if loja_id is None else str(int(loja_id))
    session.exec(text(f"SET LOCAL app.current_loja_id = {valor}"))
