import re
import unicodedata


def slugify(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    com_hifens = re.sub(r"[^a-z0-9]+", "-", sem_acento.lower())
    return com_hifens.strip("-") or "loja"
