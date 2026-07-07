import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool
from fastapi.testclient import TestClient

# Importar app.main garante que todos os models (app.models) já foram
# carregados e registrados em SQLModel.metadata antes do create_all rodar —
# sem isso, create_all silenciosamente não cria nenhuma tabela.
from app.main import app
from app.core.db import get_session


@pytest.fixture(name="session")
def session_fixture():
    """Um banco SQLite em memória, novo e isolado, por teste — substitui o
    banco único compartilhado (tests/db/test.db) que fazia os testes
    dependerem de estado deixado por execuções anteriores (ver
    docs/DIVIDA_TECNICA.md item 25)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    """TestClient com a sessão do teste injetada no lugar da sessão real —
    todo request feito por `client` enxerga exatamente o banco isolado do
    fixture `session` acima, então setup direto via `session.add(...)` e
    verificação via `client.get(...)` (ou vice-versa) sempre veem os mesmos
    dados."""
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
