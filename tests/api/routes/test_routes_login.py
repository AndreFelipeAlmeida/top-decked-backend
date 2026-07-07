from fastapi.testclient import TestClient

from app.services.EmailService import criar_token_redefinicao_senha
from app.core.security import verificar_senha


def test_login_token_sucesso(client: TestClient):
    payload_cadastro = {
        "nome": "Teste Login",
        "email": "teste.login@gmail.com",
        "senha": "minhasenha",
    }
    client.post("/api/jogadores/", json=payload_cadastro)

    login_data = {"username": "teste.login@gmail.com", "password": "minhasenha"}
    response = client.post("/api/login/token", data=login_data)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_token_senha_errada(client: TestClient):
    payload_cadastro = {
        "nome": "Teste Login Fail",
        "email": "teste.fail@gmail.com",
        "senha": "senha_correta",
    }
    client.post("/api/jogadores/", json=payload_cadastro)

    login_data = {"username": "teste.fail@gmail.com", "password": "senha_errada"}
    response = client.post("/api/login/token", data=login_data)
    assert response.status_code == 401
    assert "detail" in response.json()


def test_login_token_usuario_inexistente(client: TestClient):
    login_data = {"username": "nao.existe@example.com", "password": "qualquer"}
    response = client.post("/api/login/token", data=login_data)
    assert response.status_code == 401
    assert "detail" in response.json()


def test_login_profile_com_token_valido(client: TestClient):
    client.post(
        "/api/jogadores/",
        json={"nome": "Perfil Teste", "email": "perfil@gmail.com", "senha": "senha123"},
    )
    token = client.post(
        "/api/login/token",
        data={"username": "perfil@gmail.com", "password": "senha123"},
    ).json()["access_token"]

    r = client.get("/api/login/profile", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == "perfil@gmail.com"
    assert data["tipo"] == "jogador"


def test_login_profile_sem_token_e_negado(client: TestClient):
    r = client.get("/api/login/profile")
    assert r.status_code == 401


def test_login_profile_com_token_invalido_e_negado(client: TestClient):
    r = client.get("/api/login/profile", headers={"Authorization": "Bearer token-invalido"})
    assert r.status_code == 401


def test_esqueci_senha_sempre_responde_generico_exista_ou_nao_o_email(client: TestClient):
    """Mesma mensagem pro e-mail existente e pro inexistente — não pode dar
    pra descobrir quais e-mails estão cadastrados pela resposta."""
    client.post(
        "/api/jogadores/",
        json={"nome": "Existe", "email": "existe.esqueci@gmail.com", "senha": "senha123"},
    )

    r1 = client.post("/api/login/esqueci-senha", json={"email": "existe.esqueci@gmail.com"})
    r2 = client.post("/api/login/esqueci-senha", json={"email": "nao.existe.esqueci@gmail.com"})

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_validar_token_redefinicao_valido(client: TestClient):
    client.post(
        "/api/jogadores/",
        json={"nome": "Valida Token", "email": "valida.token@gmail.com", "senha": "senha123"},
    )
    token = criar_token_redefinicao_senha("valida.token@gmail.com")

    r = client.get("/api/login/validar-token-redefinicao", params={"token": token})
    assert r.status_code == 200
    assert r.json() == {"valido": True}


def test_validar_token_redefinicao_rejeita_token_de_outro_proposito(client: TestClient):
    """Um JWT válido (mesma chave/algoritmo) mas sem o claim `tipo` correto
    (ex.: um token de confirmação de e-mail) não pode servir pra redefinir
    senha — ver docstring de _decodificar_token_redefinicao."""
    from jose import jwt as jose_jwt
    from datetime import datetime, timedelta, timezone
    from app.core.security import SECRET_KEY, ALGORITHM

    client.post(
        "/api/jogadores/",
        json={"nome": "Outro Proposito", "email": "outro.proposito@gmail.com", "senha": "senha123"},
    )
    token_confirmacao_email = jose_jwt.encode(
        {"sub": "outro.proposito@gmail.com", "exp": datetime.now(timezone.utc) + timedelta(hours=24)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    r = client.get("/api/login/validar-token-redefinicao", params={"token": token_confirmacao_email})
    assert r.status_code == 400


def test_validar_token_redefinicao_rejeita_token_expirado(client: TestClient):
    from jose import jwt as jose_jwt
    from datetime import datetime, timedelta, timezone
    from app.core.security import SECRET_KEY, ALGORITHM

    client.post(
        "/api/jogadores/",
        json={"nome": "Expirado", "email": "expirado@gmail.com", "senha": "senha123"},
    )
    token_expirado = jose_jwt.encode(
        {
            "sub": "expirado@gmail.com",
            "tipo": "redefinir_senha",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    r = client.get("/api/login/validar-token-redefinicao", params={"token": token_expirado})
    assert r.status_code == 400


def test_redefinir_senha_com_sucesso_e_permite_login_com_a_nova_senha(client: TestClient, session):
    from sqlmodel import select
    from app.models import Usuario

    client.post(
        "/api/jogadores/",
        json={"nome": "Redefine", "email": "redefine@gmail.com", "senha": "senha_antiga"},
    )
    token = criar_token_redefinicao_senha("redefine@gmail.com")

    r = client.post(
        "/api/login/redefinir-senha",
        json={"token": token, "nova_senha": "senha_nova"},
    )
    assert r.status_code == 200

    usuario = session.exec(
        select(Usuario).where(Usuario.email == "redefine@gmail.com")
    ).first()
    assert verificar_senha("senha_nova", usuario.senha)
    assert not verificar_senha("senha_antiga", usuario.senha)

    login_antigo = client.post(
        "/api/login/token",
        data={"username": "redefine@gmail.com", "password": "senha_antiga"},
    )
    assert login_antigo.status_code == 401

    login_novo = client.post(
        "/api/login/token",
        data={"username": "redefine@gmail.com", "password": "senha_nova"},
    )
    assert login_novo.status_code == 200


def test_redefinir_senha_com_token_invalido_e_rejeitado(client: TestClient):
    r = client.post(
        "/api/login/redefinir-senha",
        json={"token": "token-totalmente-invalido", "nova_senha": "qualquer"},
    )
    assert r.status_code == 400


def test_redefinir_senha_para_email_inexistente_e_rejeitado(client: TestClient):
    token = criar_token_redefinicao_senha("fantasma@gmail.com")

    r = client.post(
        "/api/login/redefinir-senha",
        json={"token": token, "nova_senha": "qualquer"},
    )
    assert r.status_code == 400
