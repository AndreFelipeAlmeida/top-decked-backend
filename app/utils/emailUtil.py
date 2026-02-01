from jose import jwt
from datetime import datetime, timedelta, timezone
from app.core.config import settings
import os


SECRET_KEY = settings.SECURITY_SECRET_KEY
ALGORITHM = settings.SECURITY_ALGORITHM


def criar_token_confirmacao(email: str):
    expiracao = datetime.now(timezone.utc) + timedelta(hours=24)
    token = jwt.encode({"sub": email, "exp": expiracao},
                       SECRET_KEY, algorithm=ALGORITHM)
    return token
