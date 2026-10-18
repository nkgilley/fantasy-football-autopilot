import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import SessionLocal
from app.engine.pipeline import run_daily_autopilot_pipeline
from app.settings_store import get_effective_settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
DAILY_JOB_ID = "daily_fantasy_autopilot_job"


async def _scheduled_daily_job() -> None:
    logger.info("Starting scheduled daily Fantasy Autopilot job...")
    db = SessionLocal()
    try:
        await run_daily_autopilot_pipeline(
            db=db,
            trigger_source="scheduled",
            send_email=True,
            attempt_live_fp=True,
        )
    except Exception as exc:
        logger.error("Scheduled daily job failed: %s", exc)
    finally:
        db.close()


def configure_daily_scheduler() -> None:
    db = SessionLocal()
    try:
        eff = get_effective_settings(db)
        sync_time = str(eff.get("daily_sync_time", "08:00"))
        tz = str(eff.get("timezone", "America/New_York"))
    finally:
        db.close()

    try:
        hour_str, minute_str = sync_time.split(":")
        hour, minute = int(hour_str), int(minute_str)
    except Exception:
        hour, minute = 8, 0

    if scheduler.get_job(DAILY_JOB_ID):
        scheduler.remove_job(DAILY_JOB_ID)

    scheduler.add_job(
        _scheduled_daily_job,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
        id=DAILY_JOB_ID,
        replace_existing=True,
    )
    if not scheduler.running:
        scheduler.start()
    logger.info("Scheduled daily Fantasy Autopilot sync at %02d:%02d (%s)", hour, minute, tz)


def get_scheduler_status() -> dict:
    job = scheduler.get_job(DAILY_JOB_ID)
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {
        "running": scheduler.running,
        "next_run_time": next_run,
    }
