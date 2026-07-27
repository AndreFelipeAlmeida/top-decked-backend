from sqlmodel import select, text
from app.core.db import SessionDep
from app.models import Loja, Torneio, Evento
from app.services.TorneioService import apagar_torneio_completo


def apagar_loja_completa(session: SessionDep, loja: Loja) -> None:
    """Apaga a loja e toda entidade dependente: torneios (com toda a
    cascata própria deles — rodadas, inscrições, composições, pontuação
    extra), eventos, vínculos/créditos de jogador, estoque e a própria
    conta de login. Mesma filosofia de `apagar_torneio_completo`: SQL puro
    e explícito, filho antes de pai, sem depender de cascade de ORM nem de
    ON DELETE do banco (SQLite de dev/teste não aplica nenhum). Não faz
    commit — quem chama decide quando."""
    loja_id = loja.id

    torneio_ids = session.exec(select(Torneio.id).where(Torneio.loja_id == loja_id)).all()
    for torneio_id in torneio_ids:
        apagar_torneio_completo(session, torneio_id)

    evento_ids = session.exec(select(Evento.id).where(Evento.loja_id == loja_id)).all()
    for evento_id in evento_ids:
        session.exec(text("DELETE FROM metaevento WHERE evento_id = :evento_id").bindparams(evento_id=evento_id))
        session.exec(text("DELETE FROM regrapontuacaoevento WHERE evento_id = :evento_id").bindparams(evento_id=evento_id))
        session.exec(text("DELETE FROM regrapontuacaomanualevento WHERE evento_id = :evento_id").bindparams(evento_id=evento_id))
        session.exec(text("DELETE FROM pontosmanualevento WHERE evento_id = :evento_id").bindparams(evento_id=evento_id))
        session.exec(text("DELETE FROM participanteevento WHERE evento_id = :evento_id").bindparams(evento_id=evento_id))
        session.exec(text("DELETE FROM evento WHERE id = :evento_id").bindparams(evento_id=evento_id))

    session.exec(
        text("""
            DELETE FROM lojajogadororganizadortcg
            WHERE loja_jogador_link_id IN (SELECT id FROM lojajogadorlink WHERE loja_id = :loja_id)
        """).bindparams(loja_id=loja_id)
    )
    session.exec(text("DELETE FROM lojajogadorlink WHERE loja_id = :loja_id").bindparams(loja_id=loja_id))

    session.exec(text("DELETE FROM historicocredito WHERE loja_id = :loja_id").bindparams(loja_id=loja_id))

    session.exec(
        text("""
            DELETE FROM itemtransacao
            WHERE transacao_id IN (SELECT id FROM transacao WHERE loja_id = :loja_id)
        """).bindparams(loja_id=loja_id)
    )
    session.exec(text("DELETE FROM transacao WHERE loja_id = :loja_id").bindparams(loja_id=loja_id))

    session.exec(text("DELETE FROM historicoitem WHERE loja_id = :loja_id").bindparams(loja_id=loja_id))
    session.exec(text("DELETE FROM item WHERE loja_id = :loja_id").bindparams(loja_id=loja_id))
    session.exec(text("DELETE FROM categoria WHERE loja_id = :loja_id").bindparams(loja_id=loja_id))

    session.exec(text("DELETE FROM tipojogador WHERE loja_id = :loja_id").bindparams(loja_id=loja_id))
    session.exec(text("DELETE FROM temporada WHERE loja_id = :loja_id").bindparams(loja_id=loja_id))

    session.exec(text("DELETE FROM loja WHERE id = :loja_id").bindparams(loja_id=loja_id))
    session.exec(text("DELETE FROM usuario WHERE id = :usuario_id").bindparams(usuario_id=loja.usuario_id))
