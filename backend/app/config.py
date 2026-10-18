import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Yahoo OAuth 2.0 & Browser Session Fallback
    yahoo_client_id: str = ""
    yahoo_client_secret: str = ""
    yahoo_redirect_uri: str = "https://localhost:8000"
    yahoo_cookie: str = ""

    # Gmail SMTP (App Password)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_app_password: str = ""
    email_from: str = ""
    email_to: str = ""

    # Scheduler & Execution Defaults
    daily_sync_time: str = "08:00"
    timezone: str = "America/New_York"
    default_execution_mode: str = "advisory"  # "advisory" | "auto_lineup"
    dry_run: bool = True

    # Storage
    data_dir: str = "./data"

    @property
    def resolved_data_dir(self) -> Path:
        path = Path(self.data_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def sqlite_url(self) -> str:
        db_file = self.resolved_data_dir / "autopilot.db"
        return f"sqlite:///{db_file}"


settings = Settings()
