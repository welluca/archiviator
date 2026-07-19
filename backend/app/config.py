"""Application settings (pydantic-settings), lazy-loaded so tests can override env first."""

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Archiviator settings. Env vars use the ARCHIVIATOR_ prefix (e.g. ARCHIVIATOR_DATA_DIR)."""

    model_config = SettingsConfigDict(env_prefix="ARCHIVIATOR_", extra="ignore")

    data_dir: Path = Path(r"C:\archiviator-data")
    host: str = "127.0.0.1"
    port: int = 8422
    base_url: str = "https://threadripper.tail3670c0.ts.net"
    access_token_minutes: int = 15
    refresh_token_days: int = 90
    cors_origins: list[str] = ["http://localhost:5175"]
    jwt_algorithm: str = "HS256"

    _jwt_secret: str | None = PrivateAttr(default=None)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "archiviator.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def jwt_secret(self) -> str:
        """JWT signing secret: generated once and persisted to {data_dir}/secret.key."""
        if self._jwt_secret is None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            secret_file = self.data_dir / "secret.key"
            if secret_file.exists():
                secret = secret_file.read_text(encoding="utf-8").strip()
                if not secret:
                    secret = secrets.token_hex(32)
                    secret_file.write_text(secret, encoding="utf-8")
            else:
                secret = secrets.token_hex(32)
                secret_file.write_text(secret, encoding="utf-8")
            self._jwt_secret = secret
        return self._jwt_secret


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor. Call get_settings.cache_clear() to force a reload."""
    return Settings()
