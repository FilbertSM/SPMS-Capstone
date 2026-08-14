from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "SPMS API"
    API_V1_STR: str = "/api/v1"
    GOOGLE_API_KEY: str | None = None
    
    # Security
    SECRET_KEY: str = "fallback_secret_key_change_in_production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # CORS
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    FRONTEND_BASE_URL: AnyHttpUrl = "http://localhost:5173"

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Database connection string
    DATABASE_URL: str = "sqlite:///./spms.db"

    MAIL_USERNAME: str = "spms@example.com"
    MAIL_PASSWORD: str = "change-me"
    MAIL_FROM: str = "spms@example.com"
    MAIL_PORT: int = 587
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_FROM_NAME: str = "SPMS Admin"

    # Telegram alert notifications
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_BOT_USERNAME: str = "spms_alerts_bot"
    TELEGRAM_POLL_TIMEOUT_SECONDS: int = 30

    class Config:
        env_file = ".env"
        case_sensitive = True
        
settings = Settings()
