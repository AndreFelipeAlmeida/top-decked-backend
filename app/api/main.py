from fastapi import APIRouter
from app.api.routes import admin, loja, jogador, login, torneio, tipoJogador, ranking, estoque, lojaJogadorLink, enums, categoria, conquista, composicao, temporada, pontuacaoExtra, evento, tenant, pdv
from app.core.config import settings

api_router = APIRouter(prefix=settings.API_PREFIX)

# conquista.router precisa vir antes de jogador.router: ele expõe rotas literais
# como /jogadores/conquistas, e jogador.router tem uma rota /jogadores/{jogador_id}
# que, se registrada primeiro, casa com "conquistas" como se fosse o id (erro de
# parsing de int) — FastAPI resolve rotas na ordem de registro.
api_router.include_router(conquista.router)
api_router.include_router(composicao.router)
api_router.include_router(jogador.router)
api_router.include_router(loja.router)
api_router.include_router(login.router)
api_router.include_router(torneio.router)
api_router.include_router(ranking.router)
api_router.include_router(tipoJogador.router)
api_router.include_router(estoque.router)
api_router.include_router(categoria.router)
api_router.include_router(lojaJogadorLink.router)
api_router.include_router(enums.router)
api_router.include_router(temporada.router)
api_router.include_router(pontuacaoExtra.router)
api_router.include_router(evento.router)
api_router.include_router(admin.router)
api_router.include_router(tenant.router)
api_router.include_router(pdv.router)
