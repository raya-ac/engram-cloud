from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

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
    allowed_hosts: str = Field(default="")
    secure_cookies: bool | None = Field(default=None)
    session_max_age_seconds: int = Field(default=60 * 60 * 24 * 14)
    max_request_bytes: int = Field(default=2_000_000)
    auth_rate_limit_per_minute: int = Field(default=12)
    api_rate_limit_per_minute: int = Field(default=240)

    def host_allowlist(self) -> list[str]:
        configured = [host.strip().lower() for host in self.allowed_hosts.split(",") if host.strip()]
        base_host = (urlparse(self.base_url).hostname or "").lower()
        defaults = ["127.0.0.1", "localhost", "testserver"]
        if base_host:
            defaults.append(base_host)
            if not base_host.startswith("www."):
                defaults.append(f"www.{base_host}")
        return sorted(set(configured + defaults))

    def cookie_https_only(self) -> bool:
        if self.secure_cookies is not None:
            return self.secure_cookies
        return self.base_url.startswith("https://")

    def validate_runtime_security(self) -> None:
        production_like = self.base_url.startswith("https://")
        if production_like and self.secret_key in {"dev-secret-change-me", "change-me"}:
            raise RuntimeError("ENGRAM_CLOUD_SECRET_KEY must be changed before HTTPS deployment")
        if production_like and len(self.secret_key) < 32:
            raise RuntimeError("ENGRAM_CLOUD_SECRET_KEY must be at least 32 characters in production")


settings = Settings()
