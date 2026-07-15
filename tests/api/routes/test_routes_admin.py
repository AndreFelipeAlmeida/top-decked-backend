"""Testes do módulo do Administrador: bootstrap seguro do admin root via
.env, e o fluxo de pré-cadastro/aprovação de Lojas — uma Loja só consegue
autenticar depois que um Administrador aprova o cadastro."""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.db import get_session
from app.models import Administrador, Loja, Usuario
from app.services.AdministradorService import bootstrap_admin_root
from app.utils.datetimeUtil import data_agora_brasil
from app.utils.Enums import StatusAprovacaoLoja


def _login(client: TestClient, email: str, senha: str):
    r = client.post("/api/login/token", data={"username": email, "password": senha})
    # BRK-309: ver comentário equivalente em outros arquivos de teste — o
    # TestClient mantém um cookie jar persistente entre chamadas, e este
    # arquivo testa várias contas (admin, lojas diferentes) no mesmo
    # client; sem limpar aqui, o Authorization passado explicitamente nos
    # testes seria ofuscado pelo cookie da ÚLTIMA conta logada.
    client.cookies.clear()
    return r


def _criar_loja(client: TestClient, nome: str, email: str, senha: str = "senha123") -> dict:
    r = client.post(
        "/api/lojas/",
        json={"nome": nome, "endereco": "Rua X, 1", "email": email, "senha": senha},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _sessao_do_client(client: TestClient) -> Session:
    return client.app.dependency_overrides[get_session]()


def _criar_admin_autenticado(client: TestClient, email: str, senha: str = "senha-admin-123") -> dict:
    """Não existe cadastro público de Administrador (só bootstrap via .env)
    — cria direto no banco, igual o bootstrap faria."""
    session = _sessao_do_client(client)
    usuario = Usuario(email=email, tipo="admin", is_active=True, data_cadastro=data_agora_brasil())
    usuario.set_senha(senha)
    session.add(usuario)
    session.commit()
    session.refresh(usuario)

    admin = Administrador(nome="Admin Teste", usuario_id=usuario.id)
    session.add(admin)
    session.commit()

    r = _login(client, email, senha)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_bootstrap_admin_root_cria_administrador_a_partir_do_env(client: TestClient, session: Session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_EMAIL", "root@brickei.com.br")
    monkeypatch.setattr(settings, "ADMIN_SENHA", "senha-root-123")

    assert session.exec(select(Administrador)).first() is None

    bootstrap_admin_root(session)

    admin = session.exec(select(Administrador)).first()
    assert admin is not None
    assert admin.nome == "Administrador"

    usuario = session.get(Usuario, admin.usuario_id)
    assert usuario.email == "root@brickei.com.br"
    assert usuario.tipo == "admin"
    assert usuario.is_active is True

    r = _login(client, "root@brickei.com.br", "senha-root-123")
    assert r.status_code == 200, r.text

    r = client.get("/api/login/profile", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert r.status_code == 200, r.text
    assert r.json()["tipo"] == "admin"


def test_bootstrap_admin_root_e_idempotente(session: Session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_EMAIL", "root2@brickei.com.br")
    monkeypatch.setattr(settings, "ADMIN_SENHA", "senha-root-123")

    bootstrap_admin_root(session)
    bootstrap_admin_root(session)

    admins = session.exec(select(Administrador)).all()
    assert len(admins) == 1


def test_bootstrap_admin_root_sem_credenciais_no_env_nao_cria_nada(session: Session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_EMAIL", "")
    monkeypatch.setattr(settings, "ADMIN_SENHA", "")

    bootstrap_admin_root(session)

    assert session.exec(select(Administrador)).first() is None


def test_loja_pendente_nao_consegue_logar(client: TestClient) -> None:
    _criar_loja(client, "Loja Pendente", "loja.pendente@gmail.com")

    r = _login(client, "loja.pendente@gmail.com", "senha123")
    assert r.status_code == 403, r.text
    assert "pendente" in r.json()["detail"].lower()


def test_loja_rejeitada_nao_consegue_logar(client: TestClient) -> None:
    loja = _criar_loja(client, "Loja Rejeitada", "loja.rejeitada@gmail.com")
    session = _sessao_do_client(client)
    loja_db = session.get(Loja, loja["id"])
    loja_db.status = StatusAprovacaoLoja.REJEITADA
    session.commit()

    r = _login(client, "loja.rejeitada@gmail.com", "senha123")
    assert r.status_code == 403, r.text
    assert "rejeitado" in r.json()["detail"].lower()


def test_loja_aprovada_consegue_logar(client: TestClient) -> None:
    loja = _criar_loja(client, "Loja Aprovada", "loja.aprovada@gmail.com")
    session = _sessao_do_client(client)
    loja_db = session.get(Loja, loja["id"])
    loja_db.status = StatusAprovacaoLoja.APROVADA
    session.commit()

    r = _login(client, "loja.aprovada@gmail.com", "senha123")
    assert r.status_code == 200, r.text


def test_nova_loja_nasce_pendente(client: TestClient) -> None:
    loja = _criar_loja(client, "Loja Nova", "loja.nova@gmail.com")
    assert loja["status"] == "PENDENTE"


# ---------------------------------- Moderação de Lojas ----------------------------------

def test_lojas_pendentes_requer_admin(client: TestClient) -> None:
    r = client.get("/api/admin/lojas/pendentes")
    assert r.status_code == 401, r.text

    loja = _criar_loja(client, "Loja Sem Permissao", "loja.semperm@gmail.com")
    session = _sessao_do_client(client)
    loja_db = session.get(Loja, loja["id"])
    loja_db.status = StatusAprovacaoLoja.APROVADA
    session.commit()
    token = _login(client, "loja.semperm@gmail.com", "senha123").json()["access_token"]

    r = client.get("/api/admin/lojas/pendentes", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, r.text


def test_listar_aprovar_e_rejeitar_lojas_pendentes(client: TestClient) -> None:
    admin_headers = _criar_admin_autenticado(client, "admin.moderacao@brickei.com.br")

    pendente = _criar_loja(client, "Loja A Aprovar", "loja.aaprovar@gmail.com")
    outra = _criar_loja(client, "Loja A Rejeitar", "loja.arejeitar@gmail.com")

    r = client.get("/api/admin/lojas/pendentes", headers=admin_headers)
    assert r.status_code == 200, r.text
    ids_pendentes = {loja["id"] for loja in r.json()}
    assert pendente["id"] in ids_pendentes
    assert outra["id"] in ids_pendentes

    r = client.put(f"/api/admin/lojas/{pendente['id']}/aprovar", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APROVADA"

    r = client.put(f"/api/admin/lojas/{outra['id']}/rejeitar", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REJEITADA"

    # Depois de decididas, nenhuma das duas aparece mais como pendente.
    r = client.get("/api/admin/lojas/pendentes", headers=admin_headers)
    ids_pendentes = {loja["id"] for loja in r.json()}
    assert pendente["id"] not in ids_pendentes
    assert outra["id"] not in ids_pendentes

    # E a aprovada já consegue logar; a rejeitada continua bloqueada.
    r = _login(client, "loja.aaprovar@gmail.com", "senha123")
    assert r.status_code == 200, r.text
    r = _login(client, "loja.arejeitar@gmail.com", "senha123")
    assert r.status_code == 403, r.text


# ---------------------------------- CRUD Dinâmico de Entidades ----------------------------------

def test_listar_entidades_gerenciaveis(client: TestClient) -> None:
    admin_headers = _criar_admin_autenticado(client, "admin.entidades@brickei.com.br")

    r = client.get("/api/admin/entidades", headers=admin_headers)
    assert r.status_code == 200, r.text
    nomes = {entidade["nome"] for entidade in r.json()}
    assert "loja" in nomes
    assert "torneio" in nomes
    # Contas de autenticação nunca entram na allowlist genérica (senha/hash).
    assert "usuario" not in nomes
    assert "administrador" not in nomes


def test_colunas_de_entidade_descrevem_fk(client: TestClient) -> None:
    admin_headers = _criar_admin_autenticado(client, "admin.colunas@brickei.com.br")

    r = client.get("/api/admin/entidades/torneio/colunas", headers=admin_headers)
    assert r.status_code == 200, r.text
    colunas = {coluna["nome"]: coluna for coluna in r.json()}

    assert colunas["loja_id"]["chave_estrangeira"] == {"tabela": "loja", "coluna": "id"}
    assert colunas["id"]["chave_primaria"] is True
    assert colunas["conta_em_eventos"]["tipo"] == "boolean"
    # Campo sensível de outra entidade não vaza mesmo que alguém peça por
    # engano — mas "torneio" nem tem "senha", então o teste real de
    # ocultação é a entidade não aparecer em /admin/entidades (teste acima).


def test_colunas_de_entidade_nao_gerenciavel_e_rejeitado(client: TestClient) -> None:
    admin_headers = _criar_admin_autenticado(client, "admin.naogerenciavel@brickei.com.br")

    r = client.get("/api/admin/entidades/usuario/colunas", headers=admin_headers)
    assert r.status_code == 404, r.text


def test_crud_generico_de_entidade(client: TestClient) -> None:
    admin_headers = _criar_admin_autenticado(client, "admin.crud@brickei.com.br")
    loja = _criar_loja(client, "Loja CRUD Admin", "loja.crudadmin@gmail.com")

    # A Categoria "Gerais" já nasce junto da loja (POST /lojas/).
    r = client.get("/api/admin/entidades/categoria", headers=admin_headers)
    assert r.status_code == 200, r.text
    gerais = next(c for c in r.json() if c["loja_id"] == loja["id"])
    assert gerais["nome"] == "Gerais"

    r = client.post(
        "/api/admin/entidades/categoria",
        json={"nome": "Categoria Nova", "loja_id": loja["id"]},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    nova = r.json()
    assert nova["nome"] == "Categoria Nova"

    r = client.post(
        "/api/admin/entidades/categoria",
        json={"nome": "Categoria Orfa", "loja_id": 999999},
        headers=admin_headers,
    )
    assert r.status_code == 400, r.text

    r = client.put(
        f"/api/admin/entidades/categoria/{nova['id']}",
        json={"nome": "Categoria Renomeada"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "Categoria Renomeada"

    r = client.delete(f"/api/admin/entidades/categoria/{nova['id']}", headers=admin_headers)
    assert r.status_code == 204, r.text

    r = client.get("/api/admin/entidades/categoria", headers=admin_headers)
    ids = {c["id"] for c in r.json()}
    assert nova["id"] not in ids


def test_crud_generico_requer_admin(client: TestClient) -> None:
    r = client.get("/api/admin/entidades/categoria")
    assert r.status_code == 401, r.text
