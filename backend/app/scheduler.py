from datetime import datetime
import json
import logging
import time
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app.db import SessionLocal
from app.engine.pipeline import run_daily_autopilot_pipeline
from app.settings_store import get_effective_settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
DAILY_JOB_PREFIX = "daily_fantasy_autopilot_job_"
PRE_KICKOFF_JOB_PREFIX = "pre_kickoff_autopilot_job_"

# Store metadata about scheduled jobs so get_scheduler_status() can return rich labels
_job_metadata: dict[str, dict[str, Any]] = {}


def parse_daily_sync_times(raw_times: str) -> list[tuple[int, int, str]]:
    """
    Parses one or more comma-separated HH:MM strings (e.g. '08:00' or '08:00, 12:30, 18:00')
    into sorted, deduplicated (hour, minute, 'HH:MM') tuples.
    """
    parsed: dict[tuple[int, int], str] = {}
    for part in (raw_times or "08:00").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            h_str, m_str = token.split(":", 1)
            h = int(h_str.strip())
            m = int(m_str.strip())
            if 0 <= h <= 23 and 0 <= m <= 59:
                parsed[(h, m)] = f"{h:02d}:{m:02d}"
        except Exception:
            continue

    if not parsed:
        parsed[(8, 0)] = "08:00"

    return [(h, m, parsed[(h, m)]) for (h, m) in sorted(parsed.keys())]


async def _scheduled_daily_job(time_label: str = "08:00") -> None:
    logger.info("Starting scheduled daily Fantasy Autopilot job (%s)...", time_label)
    db = SessionLocal()
    try:
        await run_daily_autopilot_pipeline(
            db=db,
            trigger_source="scheduled",
            send_email=True,
            attempt_live_fp=True,
        )
    except Exception as exc:
        logger.error("Scheduled daily job (%s) failed: %s", time_label, exc)
    finally:
        db.close()


async def _scheduled_pre_kickoff_job(kickoff_ts: int, teams: list[str]) -> None:
    teams_label = ", ".join(teams[:6]) + (f" +{len(teams) - 6} more" if len(teams) > 6 else "")
    logger.info("Starting pre-kickoff Fantasy Autopilot check for %s (kickoff_ts=%s)...", teams_label, kickoff_ts)
    db = SessionLocal()
    try:
        await run_daily_autopilot_pipeline(
            db=db,
            trigger_source="pre_kickoff",
            send_email=False,
            attempt_live_fp=True,
        )
    except Exception as exc:
        logger.error("Scheduled pre-kickoff job (%s) failed: %s", kickoff_ts, exc)
    finally:
        db.close()


def configure_daily_scheduler() -> None:
    db = SessionLocal()
    try:
        eff = get_effective_settings(db)
        sync_time_raw = str(eff.get("daily_sync_time", "08:00"))
        tz_name = str(eff.get("timezone", "America/New_York"))
        pre_game_enabled = bool(eff.get("pre_game_sync_enabled", True))
        minutes_before = int(eff.get("pre_game_minutes_before", 5) or 5)
        kickoffs_raw = str(eff.get("upcoming_kickoffs_json", "[]") or "[]")
    finally:
        db.close()

    try:
        tz_obj = ZoneInfo(tz_name)
    except Exception:
        tz_name = "America/New_York"
        tz_obj = ZoneInfo(tz_name)

    # Clear previous autopilot jobs
    for job in list(scheduler.get_jobs()):
        if (
            job.id.startswith(DAILY_JOB_PREFIX)
            or job.id.startswith(PRE_KICKOFF_JOB_PREFIX)
            or job.id == "daily_fantasy_autopilot_job"
        ):
            scheduler.remove_job(job.id)
    _job_metadata.clear()

    # 1. Schedule Daily Check Time(s)
    daily_times = parse_daily_sync_times(sync_time_raw)
    for hour, minute, label in daily_times:
        job_id = f"{DAILY_JOB_PREFIX}{hour:02d}_{minute:02d}"
        scheduler.add_job(
            _scheduled_daily_job,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=tz_obj),
            kwargs={"time_label": label},
            id=job_id,
            replace_existing=True,
        )
        _job_metadata[job_id] = {
            "id": job_id,
            "type": "daily",
            "label": f"Daily Check ({label})",
            "time_str": label,
            "kickoff_time": None,
            "teams": [],
        }

    # 2. Schedule Pre-Kickoff Checks (N minutes before each distinct NFL game kickoff window)
    pre_kickoff_count = 0
    if pre_game_enabled:
        try:
            kickoff_windows = json.loads(kickoffs_raw)
            if not isinstance(kickoff_windows, list):
                kickoff_windows = []
        except Exception:
            kickoff_windows = []

        now_ts = int(time.time())
        for w in kickoff_windows:
            try:
                k_ts = int(w.get("kickoff_ts") or 0)
            except Exception:
                continue
            if k_ts <= 0:
                continue
            check_ts = k_ts - (minutes_before * 60)
            if check_ts <= now_ts:
                continue

            teams = list(w.get("teams") or [])
            check_dt = datetime.fromtimestamp(check_ts, tz=tz_obj)
            kickoff_dt = datetime.fromtimestamp(k_ts, tz=tz_obj)
            kickoff_str = kickoff_dt.strftime("%a %-I:%M %p")
            check_str = check_dt.strftime("%a %-I:%M %p")

            job_id = f"{PRE_KICKOFF_JOB_PREFIX}{k_ts}"
            scheduler.add_job(
                _scheduled_pre_kickoff_job,
                trigger=DateTrigger(run_date=check_dt, timezone=tz_obj),
                kwargs={"kickoff_ts": k_ts, "teams": teams},
                id=job_id,
                replace_existing=True,
            )
            _job_metadata[job_id] = {
                "id": job_id,
                "type": "pre_kickoff",
                "label": f"{check_str} ({minutes_before}m before {kickoff_str} kickoff)",
                "time_str": check_str,
                "kickoff_time": kickoff_str,
                "teams": teams,
            }
            pre_kickoff_count += 1

    if not scheduler.running:
        scheduler.start()

    logger.info(
        "Configured Fantasy Autopilot scheduler: %d daily check(s) [%s] + %d pre-kickoff check(s) (%dm before kickoff, tz=%s)",
        len(daily_times),
        ", ".join(t[2] for t in daily_times),
        pre_kickoff_count,
        minutes_before,
        tz_name,
    )


def get_scheduler_status() -> dict[str, Any]:
    db = SessionLocal()
    try:
        eff = get_effective_settings(db)
        sync_time_raw = str(eff.get("daily_sync_time", "08:00"))
        pre_game_enabled = bool(eff.get("pre_game_sync_enabled", True))
        minutes_before = int(eff.get("pre_game_minutes_before", 5) or 5)
    finally:
        db.close()

    daily_times = [t[2] for t in parse_daily_sync_times(sync_time_raw)]
    scheduled_jobs: list[dict[str, Any]] = []
    for job in scheduler.get_jobs():
        if not job.next_run_time:
            continue
        meta = _job_metadata.get(
            job.id,
            {
                "id": job.id,
                "type": "pre_kickoff" if job.id.startswith(PRE_KICKOFF_JOB_PREFIX) else "daily",
                "label": job.id,
                "time_str": "",
                "kickoff_time": None,
                "teams": [],
            },
        )
        scheduled_jobs.append(
            {
                **meta,
                "next_run_time": job.next_run_time.isoformat(),
            }
        )

    scheduled_jobs.sort(key=lambda j: j["next_run_time"])
    next_run = scheduled_jobs[0]["next_run_time"] if scheduled_jobs else None

    return {
        "running": scheduler.running,
        "next_run_time": next_run,
        "daily_times": daily_times,
        "pre_game_sync_enabled": pre_game_enabled,
        "pre_game_minutes_before": minutes_before,
        "scheduled_jobs": scheduled_jobs,
    }
