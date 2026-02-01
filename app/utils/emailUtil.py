from jose import jwt
from datetime import datetime, timedelta, timezone
import os


SECRET_KEY = os.getenv("SECURITY_SECRET_KEY")
ALGORITHM = os.getenv("SECURITY_ALGORITHM")

def criar_token_confirmacao(email: str):
    expiracao =  datetime.now(timezone.utc) + timedelta(hours=24)
    token = jwt.encode({"sub": email, "exp": expiracao}, SECRET_KEY, algorithm=ALGORITHM)
    return token