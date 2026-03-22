from typing import Optional
from app.models import JogadorTorneioLinkBase


class JogadorTorneioLinkPublico(JogadorTorneioLinkBase):
    game_id: Optional[str]
