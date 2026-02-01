from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine, Field
from typing import Optional
import uuid
from core.config import settings
import os


engine = create_engine(settings.DATABASE_URL, echo=True)

cartas = [
    {"nome": "Joltik", "tipo": "Pokemon", "id": "SCR 50"},
    {"nome": "Galvantula", "tipo": "Pokemon", "id": "SFA 2"},
    {"nome": "Miraidon ex", "tipo": "Pokemon", "id": "SVI 81"},
    {"nome": "Iron Hands ex", "tipo": "Pokemon", "id": "PAR 70"},
    {"nome": "Pikachu ex", "tipo": "Pokemon", "id": "SSP 57"},
    {"nome": "Iron Leaves ex", "tipo": "Pokemon", "id": "TEF 25"},
    {"nome": "Genesect", "tipo": "Pokemon", "id": "SFA 40"},

    {"nome": "Crispin", "tipo": "Treinador", "id": "SCR 133"},
    {"nome": "Pokégear 3.0", "tipo": "Item", "id": "SVI 186"},
    {"nome": "Prime Catcher", "tipo": "Item", "id": "TEF 157"},
    {"nome": "Air Balloon", "tipo": "Item", "id": "BLK 79"},
    {"nome": "Future Booster Energy Capsule", "tipo": "Item", "id": "TEF 149"},

    {"nome": "Lightning Energy", "tipo": "Energia", "id": "Lightning Energy"},
    {"nome": "Grass Energy", "tipo": "Energia", "id": "Grass Energy"},
    {"nome": "Metal Energy", "tipo": "Energia", "id": "Metal Energy"},
    {"nome": "Dreepy", "tipo": "Pokemon", "id": "TWM 128"},
    {"nome": "Drakloak", "tipo": "Pokemon", "id": "TWM 129"},
    {"nome": "Dragapult ex", "tipo": "Pokemon", "id": "TWM 130"},
    {"nome": "Duskull", "tipo": "Pokemon", "id": "PRE 35"},
    {"nome": "Dusclops", "tipo": "Pokemon", "id": "PRE 36"},
    {"nome": "Dusknoir", "tipo": "Pokemon", "id": "PRE 37"},
    {"nome": "Budew", "tipo": "Pokemon", "id": "PRE 4"},
    {"nome": "Fezandipiti ex", "tipo": "Pokemon", "id": "SFA 38"},
    {"nome": "Latias ex", "tipo": "Pokemon", "id": "SSP 76"},
    {"nome": "Hawlucha", "tipo": "Pokemon", "id": "SVI 118"},
    {"nome": "Bloodmoon Ursaluna ex", "tipo": "Pokemon", "id": "TWM 141"},

    {"nome": "Professor's Research", "tipo": "Treinador", "id": "JTG 155"},
    {"nome": "Iono", "tipo": "Treinador", "id": "PAL 185"},
    {"nome": "Boss's Orders", "tipo": "Treinador", "id": "PAL 172"},
    {"nome": "Hilda", "tipo": "Treinador", "id": "WHT 84"},
    {"nome": "Brock's Scouting", "tipo": "Treinador", "id": "JTG 146"},
    {"nome": "Buddy-Buddy Poffin", "tipo": "Item", "id": "TEF 144"},
    {"nome": "Ultra Ball", "tipo": "Item", "id": "SVI 196"},
    {"nome": "Rare Candy", "tipo": "Item", "id": "SVI 191"},
    {"nome": "Counter Catcher", "tipo": "Item", "id": "PAR 160"},
    {"nome": "Night Stretcher", "tipo": "Item", "id": "SFA 61"},
    {"nome": "Luminous Energy", "tipo": "Energia", "id": "PAL 191"},
    {"nome": "Psychic Energy", "tipo": "Energia", "id": "Psychic Energy"},
    {"nome": "Fire Energy", "tipo": "Energia", "id": "Fire Energy"},
    {"nome": "Neo Upper Energy", "tipo": "Energia", "id": "TEF 162"},
    {"nome": "Ralts", "tipo": "Pokemon", "id": "SVI 84"},
    {"nome": "Kirlia", "tipo": "Pokemon", "id": "SVI 85"},
    {"nome": "Gardevoir ex", "tipo": "Pokemon", "id": "SVI 86"},
    {"nome": "Munkidori", "tipo": "Pokemon", "id": "TWM 95"},
    {"nome": "Scream Tail", "tipo": "Pokemon", "id": "PAR 86"},
    {"nome": "Lillie's Clefairy ex", "tipo": "Pokemon", "id": "JTG 56"},
    {"nome": "Mew ex", "tipo": "Pokemon", "id": "MEW 151"},

    {"nome": "Arven", "tipo": "Treinador", "id": "OBF 186"},
    {"nome": "Earthen Vessel", "tipo": "Item", "id": "PAR 163"},
    {"nome": "Nest Ball", "tipo": "Item", "id": "SVI 181"},
    {"nome": "Bravery Charm", "tipo": "Item", "id": "PAL 173"},
    {"nome": "Technical Machine: Evolution", "tipo": "Item", "id": "PAR 178"},
    {"nome": "Artazon", "tipo": "Estádio", "id": "PAL 171"},
    {"nome": "Darkness Energy", "tipo": "Energia", "id": "Dark Energy"}
]


class Carta(SQLModel, table=True):
    id: Optional[str] = Field(
        default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    nome: Optional[str] = Field(default=None, nullable=True)
    tipo: Optional[str] = Field(default=None, nullable=True)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def inserir_cartas():
    with Session(engine) as session:
        for carta in cartas:
            carta = Carta(**carta)
            if session.get(Carta, carta.id):
                break
            session.add(carta)
        session.commit()


SessionDep = Annotated[Session, Depends(get_session)]
