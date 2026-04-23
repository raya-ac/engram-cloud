from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENGRAM_CLOUD_", env_file=".env", extra="ignore")

    secret_key: str = Field(default="dev-secret-change-me")
    base_url: str = Field(default="http://127.0.0.1:8090")
    postgres_dsn: str = Field(default="postgresql+psycopg://engram:engram@localhost:5432/engram_cloud")
    engram_postgres_dsn: str = Field(default="postgresql://engram:engram@localhost:5432/engram_cloud")
    github_client_id: str = Field(default="")
    github_client_secret: str = Field(default="")
    data_dir: Path = Field(default=Path("./data"))


settings = Settings()
