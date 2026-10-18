from typing import Any
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting


SETTING_KEYS = {
    "yahoo_client_id": lambda: settings.yahoo_client_id,
    "yahoo_client_secret": lambda: settings.yahoo_client_secret,
    "yahoo_redirect_uri": lambda: settings.yahoo_redirect_uri,
    "yahoo_cookie": lambda: settings.yahoo_cookie,
    "smtp_host": lambda: settings.smtp_host,
    "smtp_port": lambda: str(settings.smtp_port),
    "smtp_username": lambda: settings.smtp_username,
    "smtp_app_password": lambda: settings.smtp_app_password,
    "email_from": lambda: settings.email_from,
    "email_to": lambda: settings.email_to,
    "daily_sync_time": lambda: settings.daily_sync_time,
    "timezone": lambda: settings.timezone,
    "default_execution_mode": lambda: settings.default_execution_mode,
    "dry_run": lambda: "true" if settings.dry_run else "false",
}


def get_effective_settings(db: Session) -> dict[str, Any]:
    rows = {row.key: row.value for row in db.query(AppSetting).all()}
    result: dict[str, Any] = {}
    for key, env_getter in SETTING_KEYS.items():
        val = rows.get(key)
        if val is None or val == "":
            val = env_getter()
        result[key] = val

    result["smtp_port"] = int(result["smtp_port"] or 587)
    result["dry_run"] = str(result["dry_run"]).lower() in ("true", "1", "yes")
    return result


def update_settings(db: Session, updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if key not in SETTING_KEYS:
            continue
        if value is None:
            continue
        str_val = str(value).strip()
        # Do not overwrite secrets with masked placeholders
        if key in ("yahoo_client_secret", "smtp_app_password", "yahoo_cookie") and str_val.startswith("••••"):
            continue
        existing = db.query(AppSetting).filter(AppSetting.key == key).first()
        if existing:
            existing.value = str_val
        else:
            db.add(AppSetting(key=key, value=str_val))
    db.commit()
    return get_effective_settings(db)
