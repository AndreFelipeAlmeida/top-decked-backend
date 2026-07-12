from typing import List, Optional, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
import os


class Settings(BaseSettings):
    API_PREFIX: str = '/api'
    DEBUG: bool = False

    DATABASE_URL: Optional[str] = ""
    ALLOWED_ORIGINS: Union[str, List[str]] = ""

    SECURITY_SECRET_KEY: str = ""
    SECURITY_ALGORITHM: str = "HS256"
    SECURITY_TOKEN_EXPIRATION: int = 30
    POKEMONTCG_IO_API_KEY: str = ""

    RESEND_API_KEY: str = ""
    
    MAIL_FROM: str = ""
    MAIL_FROM_NAME: str = "Brickei"

    FRONTEND_URL: str = ""

    ADMIN_EMAIL: str = ""
    ADMIN_SENHA: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    def __init__(self, **values):
        super().__init__(**values)
        if not self.DEBUG:
            db_user = os.getenv("DB_USER")
            db_password = os.getenv("DB_PASSWORD")
            db_host = os.getenv("DB_HOST")
            db_port = os.getenv("DB_PORT", "5432")
            db_name = os.getenv("DB_NAME")

            if all([db_user, db_password, db_host, db_name]):
                self.DATABASE_URL = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

            # Segurança e APIs (Sobrescreve apenas se existir no ambiente)
            self.API_PREFIX = os.getenv("API_PREFIX", self.API_PREFIX)
            self.SECURITY_SECRET_KEY = os.getenv(
                "SECURITY_SECRET_KEY", self.SECURITY_SECRET_KEY)
            self.SECURITY_ALGORITHM = os.getenv(
                "SECURITY_ALGORITHM", self.SECURITY_ALGORITHM)
            self.SECURITY_TOKEN_EXPIRATION = int(
                os.getenv("SECURITY_TOKEN_EXPIRATION", str(self.SECURITY_TOKEN_EXPIRATION)))
            self.POKEMONTCG_IO_API_KEY = os.getenv(
                "POKEMONTCG_IO_API_KEY", self.POKEMONTCG_IO_API_KEY)

            # Email
            self.RESEND_API_KEY = os.getenv("RESEND_API_KEY", self.RESEND_API_KEY)
            self.MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", self.MAIL_FROM_NAME)
            self.MAIL_FROM = os.getenv("MAIL_FROM", self.MAIL_FROM)

            # Frontend
            self.FRONTEND_URL = os.getenv("FRONTEND_URL", self.FRONTEND_URL)
            self.ALLOWED_ORIGINS = os.getenv(
                "ALLOWED_ORIGINS", self.ALLOWED_ORIGINS)

            self.ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", self.ADMIN_EMAIL)
            self.ADMIN_SENHA = os.getenv("ADMIN_SENHA", self.ADMIN_SENHA)

    @field_validator("ALLOWED_ORIGINS", mode="before")
    def parse_allowed_origins(cls, v):
        if isinstance(v, str):
            return v.split(",") if v else []
        return v


settings = Settings()
