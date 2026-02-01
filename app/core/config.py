from typing import List
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    API_PREFIX: str = '/api'
    DEBUG: bool = False

    DATABASE_URL: str
    ALLOWED_ORIGINS: str = ""

    SECURITY_SECRET_KEY: str
    SECURITY_ALGORITHM: str
    SECURITY_TOKEN_EXPIRATION: int
    POKEMONTCG_IO_API_KEY: str

    # Email
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str

    FRONTEND_URL: str
    FRONTEND_PORT: str

    @field_validator("ALLOWED_ORIGINS")
    def parse_allowed_origins(cls, v: str) -> List[str]:
        return v.split(",") if v else []

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
