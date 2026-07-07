from pydantic import BaseModel


class EsqueciSenhaDTO(BaseModel):
    email: str


class RedefinirSenhaDTO(BaseModel):
    token: str
    nova_senha: str
