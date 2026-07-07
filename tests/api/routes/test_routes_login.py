from fastapi.testclient import TestClient


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
