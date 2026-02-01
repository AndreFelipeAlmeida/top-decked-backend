from sqlmodel import SQLModel

class CreditoCreate(SQLModel):
    jogador_id: int
    quantidade: float

class CreditoUpdate(SQLModel):
    quantidade: float