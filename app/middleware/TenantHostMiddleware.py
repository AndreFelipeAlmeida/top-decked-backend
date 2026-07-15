import time
from typing import Callable

from sqlmodel import Session, select
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.db import engine
from app.models import Loja

_TTL_SEGUNDOS = 30


class TenantHostMiddleware:
    """ASGI middleware (BRK-307): resolve o tenant (loja) a partir do
    cabeçalho `Host`, antes de qualquer roteamento ou autenticação — por
    isso é middleware ASGI puro, não uma dependency do FastAPI (dependency
    só roda depois que uma rota já foi escolhida).

    Regras de negócio:
    - Host igual a `settings.ROOT_DOMAIN` (ou `localhost`/`127.0.0.1`, pra
      dev local) = modo global: `request.state.loja_id = None`, descoberta
      cross-tenant continua funcionando normalmente.
    - Host `{slug}.ROOT_DOMAIN` = modo travado: `request.state.loja_id`
      recebe o id daquela loja.
    - `{slug}.ROOT_DOMAIN` cujo slug não corresponde a nenhuma loja: a
      requisição é cortada AQUI com 404 explícito — nunca cai pra modo
      global silenciosamente (o usuário acharia que a loja existe mas está
      sem torneios, em vez de "esse endereço não existe").
    - Qualquer outro host (não é o domínio raiz nem um subdomínio dele —
      ex.: acesso direto por IP em algum ambiente) é tratado como global,
      já que tecnicamente não é "um subdomínio inexistente", é só um host
      fora do esquema de tenant.

    `session_factory` é injetável de propósito (default: sessão real via
    `app.core.db.engine`) — testes montam uma instância própria do
    middleware apontando pro banco isolado do teste, em vez de bater no
    banco de verdade da aplicação (que middleware nenhum enxerga através
    de `app.dependency_overrides`, já que roda fora da injeção de
    dependência do FastAPI)."""

    def __init__(
        self,
        app: ASGIApp,
        root_domain: str,
        session_factory: Callable[[], Session] | None = None,
    ):
        self.app = app
        self.root_domain = root_domain.lower()
        self._session_factory = session_factory or (lambda: Session(engine))
        # Cache por instância (não módulo): cada middleware aponta pro seu
        # próprio banco via session_factory, então o cache também precisa
        # ser isolado — senão um teste "contaminaria" outro (ou pior, a
        # aplicação real) com um resultado cacheado de um banco diferente.
        self._cache: dict[str, tuple[int | None, float]] = {}

    def _resolver_loja_id_por_slug(self, slug: str) -> int | None:
        agora = time.monotonic()
        cacheado = self._cache.get(slug)
        if cacheado is not None and cacheado[1] > agora:
            return cacheado[0]

        with self._session_factory() as session:
            loja_id = session.exec(select(Loja.id).where(Loja.slug == slug)).first()

        self._cache[slug] = (loja_id, agora + _TTL_SEGUNDOS)
        return loja_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        host = headers.get(b"host", b"").decode("latin-1").split(":")[0].lower()

        slug = self._extrair_slug(host)

        state = scope.setdefault("state", {})
        if slug is None:
            state["loja_id"] = None
        else:
            loja_id = self._resolver_loja_id_por_slug(slug)
            if loja_id is None:
                resposta = JSONResponse({"detail": "Loja não encontrada"}, status_code=404)
                await resposta(scope, receive, send)
                return
            state["loja_id"] = loja_id

        await self.app(scope, receive, send)

    def _extrair_slug(self, host: str) -> str | None:
        if not host or host == self.root_domain or host in ("localhost", "127.0.0.1"):
            return None

        sufixo = f".{self.root_domain}"
        if not host.endswith(sufixo):
            return None

        subdominio = host[: -len(sufixo)]
        if subdominio in ("", "www"):
            return None
        return subdominio
