from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/cloudnotes"
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    JWT_EXPIRE_MINUTES: int = 60

    class Config:
        env_file = ".env"


settings = Settings()
