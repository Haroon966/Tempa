from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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
    # External HTTPS origin (Cloudflare Tunnel / reverse proxy). Used for OAuth
    # redirects, email links, and anything browsers/third parties must reach.
    # Keep tempa_webhook_base_url as the Docker-internal WhatsApp callback.
    tempa_public_base_url: str = ""
    tempa_cors_origin: str = "*"

    def resolve_public_base_url(self) -> str:
        public = (self.tempa_public_base_url or "").strip().rstrip("/")
        if public:
            return public
        return f"http://localhost:{self.tempa_daemon_port}"
    evolution_api_url: str = "http://localhost:8080"
    evolution_api_key: str = "tempa-evolution-key"
    tempa_instance_name: str = "tempa"
    whatsapp_owner_number: str = ""
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_owner_user_id: str = ""
    slack_allowed_user_ids: str = ""
    slack_allow_all: bool = False
    slack_presence_channel_id: str = "C0AU4DPFG21"
    slack_presence_channel_name: str = "presence"
    slack_presence_llm_model: str = "llama-3.1-8b-instant"
    vector_db: str = "chroma"
    calendar_poll_seconds: int = 120
    meet_trigger_before_minutes: int = 2
    meet_alone_grace_seconds: int = 300
    reminder_minutes_before: int = 10
    meet_auto_join_on_reminder: bool = True
    meet_auto_join_enabled: bool = True
    meet_skip_keywords: list[str] = ["focus time", "ooo", "out of office"]
    meet_retention_days: int = 90
    meet_auto_send_summary_whatsapp: bool = False
    meet_auto_send_summary_slack: bool = True
    meet_auto_send_summary_email: bool = True
    meet_punjab_daily_sync_slack_channel: str = "region-punjab"
    meet_admission_timeout_seconds: int = 600
    meet_record_video: bool = True
    meet_record_video_width: int = 1280
    meet_record_video_height: int = 720
    meet_system_capture_enabled: bool = True
    meet_system_capture_fps: int = 30
    meet_browser_audio_fallback: bool = False
    meet_pulse_monitor_source: str = "meet_sink_0.monitor"
    meet_max_concurrent: int = 10
    meet_virtual_camera_enabled: bool = True
    meet_virtual_camera_path: Path = Path("config/assets/animated_tempa.mjpeg")
    meet_av_test_enabled: bool = False
    meet_youtube_upload_enabled: bool = False
    meet_youtube_privacy: str = "unlisted"
    meet_calendar_lookback_hours: int = 12
    meet_copilot_whatsapp_notify: bool = False
    meet_chat_prefix: str = "[via Tempa]"

    @field_validator("meet_max_concurrent")
    @classmethod
    def _clamp_meet_max_concurrent(cls, value: int) -> int:
        return max(1, min(int(value), 16))
    tempa_timezone: str = "Asia/Karachi"
    gmail_poll_interval_seconds: int = 120
    calendar_poll_interval_seconds: int = 300
    github_app_id: str = ""
    github_private_key: str = ""
    github_webhook_secret: str = ""
    github_token: str = ""
    github_repos: str = ""
    tempa_qa_enabled: bool = True
    tempa_qa_scan_interval_minutes: int = 60
    tempa_qa_max_branches_per_repo: int = 50
    tempa_qa_deep_review_mode: str = "lite"
    anthropic_api_key: str = ""
    tempa_qa_claude_model: str = "claude-sonnet-4-20250514"
    cursor_api_key: str = ""
    tempa_qa_cursor_model: str = "composer-2.5"
    tempa_cursor_progress_interval_sec: int = 120
    tempa_cursor_job_timeout_sec: int = 7200
    tempa_cursor_max_parallel: int = 8
    tempa_cursor_ci_fix_max: int = 3
    tempa_cursor_worktree_root: Path = Path("/repos/tempa-worktrees")
    tempa_cursor_escalate_slack_ids: str = ""
    tempa_coordinator: str = "langgraph"
    tempa_adk_spike: bool = False
    tempa_hermes_disable_terminal: bool = True
    tempa_hermes_max_iterations: int = 24
    tempa_hermes_cron_enabled: bool = False
    tempa_self_improve: bool = True
    varys_orchestrator_enabled: bool = False
    varys_tick_seconds: int = 270
    varys_harness_db: Path = Path("./data/harness/harness.db")
    varys_vault_dir: Path = Path("./data/vault")
    varys_agent_name: str = "Tempa"
    varys_owner_name: str = ""
    notion_api_key: str = ""
    notion_harness_db_id: str = ""
    notion_enabled: bool = False
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_enabled: bool = False
    jira_default_project: str = ""
    jira_ticket_enabled: bool = True
    jira_ticket_rate_limit: int = 10
    coolify_base_url: str = "http://host.docker.internal:8000"
    coolify_api_token: str = ""
    coolify_enabled: bool = False
    coolify_server_uuid: str = ""
    coolify_project_uuid: str = ""
    coolify_github_app_uuid: str = ""
    coolify_deploy_key_uuid: str = ""
    coolify_wildcard_domain: str = ""
    claude_code_path: str = "claude"
    varys_claude_cli_only: bool = True

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

    def resolved_virtual_camera_path(self) -> Path | None:
        if not self.meet_virtual_camera_enabled:
            return None
        from tempa.meet.virtual_camera import default_mjpeg_path, prepare_virtual_camera_file

        path = self.meet_virtual_camera_path
        if not path.is_absolute():
            path = self.project_root / path
        if path.is_file() and path.stat().st_size > 1000:
            return path.resolve()
        prepared = prepare_virtual_camera_file(dest=path if path.suffix.lower() == ".mjpeg" else default_mjpeg_path())
        if prepared:
            return prepared
        static = self.project_root / "config/assets/animated_tempa.y4m"
        return static.resolve() if static.is_file() else None

    def resolved_silent_fake_audio_path(self) -> Path | None:
        path = self.project_root / "config/assets/silent_48k.wav"
        return path if path.is_file() else None

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
            self.sessions_dir / "slack",
            self.sessions_dir / "presence",
            self.sessions_dir / "jira",
            self.sessions_dir / "qa",
            self.tempa_data_dir / "qa" / "worktrees",
            self.tempa_data_dir / "cursor_jobs",
            self.tempa_data_dir / "skills" / "auto",
            self.tempa_data_dir / "skills" / "archive",
            self.tempa_data_dir / "hermes" / "skills",
            self.db_path.parent,
            self.varys_harness_db.parent,
            self.varys_vault_dir,
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
    if not settings.varys_harness_db.is_absolute():
        settings.varys_harness_db = (settings.project_root / settings.varys_harness_db).resolve()
    if not settings.varys_vault_dir.is_absolute():
        settings.varys_vault_dir = (settings.project_root / settings.varys_vault_dir).resolve()
    settings.ensure_dirs()
    return settings
