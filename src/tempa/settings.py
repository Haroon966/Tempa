from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    groq_api_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    tempa_data_dir: Path = Path("./data")
    tempa_daemon_port: int = 8787
    tempa_bind_host: str = "127.0.0.1"
    tempa_webhook_base_url: str = ""
    tempa_cors_origin: str = "*"
    evolution_api_url: str = "http://localhost:8080"
    evolution_api_key: str = "tempa-evolution-key"
    tempa_instance_name: str = "tempa"
    whatsapp_owner_number: str = ""
    vector_db: str = "chroma"
    calendar_poll_seconds: int = 30
    meet_trigger_before_minutes: int = 2
    meet_trigger_after_start_minutes: int = 15
    meet_alone_grace_seconds: int = 300
    reminder_minutes_before: int = 10
    meet_auto_join_on_reminder: bool = True

    @property
    def project_root(self) -> Path:
        return _project_root()

    @property
    def config_dir(self) -> Path:
        return self.project_root / "config"

    @property
    def vector_dir(self) -> Path:
        return self.tempa_data_dir / "vector"

    @property
    def meetings_dir(self) -> Path:
        return self.tempa_data_dir / "meetings"

    @property
    def sessions_dir(self) -> Path:
        return self.tempa_data_dir / "sessions"

    @property
    def google_token_path(self) -> Path:
        return self.sessions_dir / "google" / "token.json"

    @property
    def gmail_token_path(self) -> Path:
        return self.sessions_dir / "gmail" / "token.json"

    @property
    def google_storage_state_path(self) -> Path:
        return self.sessions_dir / "google" / "storage_state.json"

    @property
    def db_path(self) -> Path:
        return self.tempa_data_dir / "db" / "tempa.db"

    def ensure_dirs(self) -> None:
        for path in (
            self.tempa_data_dir,
            self.vector_dir,
            self.meetings_dir,
            self.sessions_dir / "google",
            self.sessions_dir / "gmail",
            self.sessions_dir / "whatsapp",
            self.db_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def groq_key_path(self) -> Path:
        return self.sessions_dir / "groq.key"

    def load_groq_api_key(self) -> str:
        if self.groq_api_key:
            return self.groq_api_key
        try:
            from tempa.security.sessions import read_secret_file

            key = read_secret_file("groq.key")
            if key:
                return key
        except Exception:
            pass
        key_path = self.groq_key_path()
        if key_path.exists():
            return key_path.read_text(encoding="utf-8").strip()
        return ""


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.tempa_data_dir.is_absolute():
        settings.tempa_data_dir = (settings.project_root / settings.tempa_data_dir).resolve()
    settings.ensure_dirs()
    return settings
