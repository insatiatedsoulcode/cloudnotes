from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/cloudnotes"
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    JWT_EXPIRE_MINUTES: int = 15           # access token — short-lived, not revocable
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30   # refresh token — long-lived, stored in DB
    REDIS_URL: str = "redis://localhost:6379"

    # Email / SMTP — defaults match MailHog (local dev mock)
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    EMAIL_FROM: str = "noreply@cloudnotes.local"
    APP_BASE_URL: str = "http://localhost:8000"

    # File storage — swap to "s3" when ready (F-10b)
    STORAGE_BACKEND: str = "local"
    UPLOADS_DIR: str = "./uploads"

    # Logging — "text" for human-readable dev output; "json" for CloudWatch / Datadog
    LOG_FORMAT: str = "text"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
