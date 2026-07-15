from app.core.config import settings
from app.core.db import create_db_and_tables, engine
from app.api.main import api_router
from app.middleware.TenantHostMiddleware import TenantHostMiddleware
from app.services.AdministradorService import bootstrap_admin_root
from app.services.ConquistaService import seed_conquistas_catalogo
from app.services.PokemonCatalogoService import garantir_catalogo_atualizado
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI
from contextlib import asynccontextmanager
from sqlmodel import Session
import os


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        bootstrap_admin_root(session)
        seed_conquistas_catalogo(session)
        garantir_catalogo_atualizado(session)
    yield


app = FastAPI(lifespan=lifespan,
              openapi_url=f"{settings.API_PREFIX}/openapi.json",
              docs_url=f"{settings.API_PREFIX}/docs",
              redoc_url=f"{settings.API_PREFIX}/redoc")

UPLOAD_DIR = "app/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# TenantHostMiddleware adicionado ANTES do CORSMiddleware de propósito:
# add_middleware empilha em LIFO (o último adicionado fica por FORA), então
# CORS precisa ser o mais externo pra injetar os headers mesmo numa
# resposta 404 que o TenantHostMiddleware corta antes de chegar nas rotas
# (sem isso, o 404 de "loja não encontrada" apareceria pro browser como um
# erro de rede genérico em vez do JSON de verdade, em requests cross-origin
# de um subdomínio pro outro).
app.add_middleware(TenantHostMiddleware, root_domain=settings.ROOT_DOMAIN)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
