from fastapi import APIRouter
from app.api.routes import loja, jogador, login, torneio, tipoJogador, ranking, estoque, credito
from app.core.config import settings

api_router = APIRouter(prefix=settings.API_PREFIX)

api_router.include_router(jogador.router)
api_router.include_router(loja.router)
api_router.include_router(login.router)
api_router.include_router(torneio.router)
api_router.include_router(ranking.router)
api_router.include_router(tipoJogador.router)
api_router.include_router(estoque.router)
api_router.include_router(credito.router)
