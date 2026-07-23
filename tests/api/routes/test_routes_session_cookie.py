from fastapi.testclient import TestClient

from app.core.config import settings


def _criar_jogador_e_logar(client: TestClient, email: str) -> None:
    client.post("/api/jogadores/", json={"nome": "Cookie Jogador", "email": email, "senha": "senha123"})
    r = client.post("/api/login/token", data={"username": email, "password": "senha123"})
    assert r.status_code == 200, r.text


def test_login_seta_cookie_de_sessao_httponly_e_cookie_csrf_legivel(client: TestClient):
    _criar_jogador_e_logar(client, "cookie.setcookie@gmail.com")

    # httpx/Starlette TestClient expõe os Set-Cookie crus só na resposta do
    # próprio request que os emitiu — refazemos o login aqui pra inspecionar
    # os headers, já que a chamada acima (no helper) descarta a Response.
    r = client.post("/api/login/token", data={"username": "cookie.setcookie@gmail.com", "password": "senha123"})
    cookies_emitidos = r.headers.get_list("set-cookie")
    assert len(cookies_emitidos) == 2

    cookie_sessao = next(c for c in cookies_emitidos if c.startswith("access_token="))
    cookie_csrf = next(c for c in cookies_emitidos if c.startswith("csrf_token="))

    assert "HttpOnly" in cookie_sessao
    assert "HttpOnly" not in cookie_csrf  # frontend precisa ler esse via JS
    assert "SameSite=lax" in cookie_sessao
    assert "SameSite=lax" in cookie_csrf


def test_cookie_ganha_domain_localhost_quando_root_domain_e_localhost(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ROOT_DOMAIN", "localhost")

    r = client.post(
        "/api/jogadores/", json={"nome": "X", "email": "cookie.rootlocalhost@gmail.com", "senha": "senha123"}
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/login/token", data={"username": "cookie.rootlocalhost@gmail.com", "password": "senha123"}
    )
    cookie_sessao = next(c for c in r.headers.get_list("set-cookie") if c.startswith("access_token="))
    assert "Domain=.localhost" in cookie_sessao


def test_cookie_ganha_domain_localtest_me_quando_root_domain_e_localtest_me(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ROOT_DOMAIN", "localtest.me")

    r = client.post(
        "/api/jogadores/", json={"nome": "X", "email": "cookie.rootlocaltestme@gmail.com", "senha": "senha123"}
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/login/token", data={"username": "cookie.rootlocaltestme@gmail.com", "password": "senha123"}
    )
    cookie_sessao = next(c for c in r.headers.get_list("set-cookie") if c.startswith("access_token="))
    assert "Domain=.localtest.me" in cookie_sessao


def test_requisicao_mutavel_via_cookie_sem_csrf_e_rejeitada(client: TestClient):
    _criar_jogador_e_logar(client, "cookie.semcsrf@gmail.com")
    # client.cookies agora carrega access_token/csrf_token (não foram
    # limpos) — a requisição abaixo manda o cookie automaticamente, mas
    # nenhum header X-CSRF-Token.
    r = client.put("/api/jogadores/", json={"nome": "Tentando Mudar"})
    assert r.status_code == 403
    assert "CSRF" in r.json()["detail"]


def test_requisicao_mutavel_via_cookie_com_csrf_correto_e_aceita(client: TestClient):
    _criar_jogador_e_logar(client, "cookie.comcsrf@gmail.com")
    csrf_token = client.cookies.get("csrf_token")
    assert csrf_token

    r = client.put(
        "/api/jogadores/",
        json={"nome": "Nome Atualizado"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "Nome Atualizado"


def test_requisicao_mutavel_via_cookie_com_csrf_errado_e_rejeitada(client: TestClient):
    _criar_jogador_e_logar(client, "cookie.csrferrado@gmail.com")

    r = client.put(
        "/api/jogadores/",
        json={"nome": "Tentando Mudar"},
        headers={"X-CSRF-Token": "valor-forjado-qualquer"},
    )
    assert r.status_code == 403


def test_get_via_cookie_nao_exige_csrf(client: TestClient):
    """GET nunca muda estado — exigir CSRF nele só quebraria navegação
    normal (abrir um link) sem proteger nada de verdade."""
    _criar_jogador_e_logar(client, "cookie.getsemcsrf@gmail.com")

    r = client.get("/api/login/profile")
    assert r.status_code == 200


def test_requisicao_mutavel_com_authorization_explicito_nao_exige_csrf(client: TestClient):
    """Um cliente que manda Authorization explicitamente (script, app
    mobile) não é o alvo de um ataque CSRF (que só consegue forjar o envio
    automático do cookie, nunca um header arbitrário) — ver comentário em
    app.dependencies.retornar_usuario_atual."""
    client.post(
        "/api/jogadores/", json={"nome": "Bearer Only", "email": "cookie.beareronly@gmail.com", "senha": "senha123"}
    )
    token = client.post(
        "/api/login/token", data={"username": "cookie.beareronly@gmail.com", "password": "senha123"}
    ).json()["access_token"]
    client.cookies.clear()

    r = client.put(
        "/api/jogadores/",
        json={"nome": "Nome Via Bearer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text


def test_logout_limpa_cookies_de_sessao(client: TestClient):
    _criar_jogador_e_logar(client, "cookie.logout@gmail.com")
    assert client.cookies.get("access_token")

    r = client.post("/api/login/logout")
    assert r.status_code == 200

    cookies_de_expiracao = r.headers.get_list("set-cookie")
    assert any(c.startswith("access_token=") and "Max-Age=0" in c for c in cookies_de_expiracao)
    assert any(c.startswith("csrf_token=") and "Max-Age=0" in c for c in cookies_de_expiracao)

    # Regressão: um Set-Cookie de expiração cujos atributos de segurança
    # (httponly/secure/samesite) não batem EXATAMENTE com os do cookie
    # original não é reconhecido como o mesmo cookie por um cliente HTTP
    # real — o client jar precisa ficar realmente vazio, não só a resposta
    # do logout "parecer certa".
    assert "access_token" not in client.cookies
    assert "csrf_token" not in client.cookies

    r_profile = client.get("/api/login/profile")
    assert r_profile.status_code == 401
