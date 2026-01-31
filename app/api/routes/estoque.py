from fastapi import APIRouter, Depends, UploadFile, File, Request
import os
from typing import Annotated
from sqlalchemy import JSON, func
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.schemas.Loja import LojaCriar, LojaPublico, LojaAtualizar, LojaPublicoTorneios
from app.models import Loja, Torneio
from app.models import Usuario
from sqlmodel import select
from app.utils.UsuarioUtil import verificar_novo_usuario
from app.utils.emailUtil import criar_token_confirmacao
from app.utils.datetimeUtil import data_agora_brasil
from app.core.security import TokenData
from app.dependencies import retornar_loja_atual
from datetime import datetime

from app.core.security import fastmail
from fastapi_mail import MessageSchema
from app.utils.Enums import StatusTorneio

router = APIRouter(
    prefix="/lojas/estoque",
    tags=["Lojas"])
