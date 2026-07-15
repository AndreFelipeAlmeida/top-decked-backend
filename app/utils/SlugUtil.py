import re
import unicodedata


def slugify(texto: str) -> str:
    """Normaliza um texto livre pro formato de slug de URL (BRK-305):
    minúsculo, sem acentos, só `[a-z0-9-]`. Não garante unicidade sozinho —
    isso é responsabilidade de quem chama (ver `app/api/routes/loja.py` e a
    migration de backfill do slug), já que depende do que já existe no
    banco no momento da chamada."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    com_hifens = re.sub(r"[^a-z0-9]+", "-", sem_acento.lower())
    return com_hifens.strip("-") or "loja"
