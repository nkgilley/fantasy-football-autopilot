from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db, init_db
from app.engine.optimizer import solve_optimal_lineup
from app.engine.pipeline import (
    SCORING_LABELS,
    _enrich_player_with_fp,
    apply_optimal_lineup_for_league,
    run_daily_autopilot_pipeline,
)
from app.fantasypros.scraper import fetch_fantasypros_weekly_index
from app.models import (
    FreeAgentCandidate,
    League,
    MatchupSnapshot,
    RecommendationRun,
    RosterPlayer,
)
from app.notifications.email import send_smtp_email
from app.scheduler import configure_daily_scheduler, get_scheduler_status, scheduler
from app.settings_store import get_effective_settings, update_settings
from app.yahoo.auth import (
    build_yahoo_authorize_url,
    exchange_code_for_token,
    get_oauth_status,
    save_yahoo_cookie,
)
from app.yahoo.client import get_yahoo_client
from app.yahoo.writer import build_roster_put_xml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        has_leagues = db.query(League).count() > 0
        if not has_leagues:
            logger.info("Seeding initial multi-league data & FantasyPros recommendations...")
            await run_daily_autopilot_pipeline(
                db=db,
                trigger_source="startup",
                send_email=False,
                attempt_live_fp=True,
            )
    finally:
        db.close()

    configure_daily_scheduler()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Yahoo Fantasy Football Autopilot",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExecutionModePayload(BaseModel):
    execution_mode: str  # "advisory" | "auto_lineup"


class SyncRequestPayload(BaseModel):
    send_email: bool = False
    attempt_live_fp: bool = True


class SettingsUpdatePayload(BaseModel):
    yahoo_client_id: str | None = None
    yahoo_client_secret: str | None = None
    yahoo_redirect_uri: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_app_password: str | None = None
    email_from: str | None = None
    email_to: str | None = None
    daily_sync_time: str | None = None
    timezone: str | None = None
    default_execution_mode: str | None = None
    dry_run: bool | None = None


class YahooCodePayload(BaseModel):
    code: str


class SendEmailPayload(BaseModel):
    recipient: str | None = None


def _serialize_player(p: RosterPlayer) -> dict[str, Any]:
    return {
        "player_key": p.player_key,
        "name": p.name,
        "team": p.team,
        "position": p.position,
        "eligible_positions": json.loads(p.eligible_positions_json or "[]"),
        "current_slot": p.current_slot,
        "optimal_slot": p.optimal_slot,
        "status": p.status,
        "injury_note": p.injury_note,
        "bye_week": p.bye_week,
        "opponent": p.opponent,
        "game_time": p.game_time,
        "is_locked": "Locked" in (p.game_time or ""),
        "yahoo_proj": p.yahoo_proj,
        "fp_ecr": p.fp_ecr,
        "fp_pos_rank": p.fp_pos_rank,
        "fp_proj": p.fp_proj,
        "fp_tier": p.fp_tier,
        "ros_ecr": getattr(p, "ros_ecr", 999) or 999,
        "ros_pos_rank": getattr(p, "ros_pos_rank", "") or "",
        "is_starter_current": p.is_starter_current,
        "is_starter_optimal": p.is_starter_optimal,
        "action_needed": p.action_needed,
        "swap_reason": p.swap_reason,
    }


def _build_swaps_from_roster(players: list[RosterPlayer]) -> list[dict[str, Any]]:
    promoted = sorted(
        [p for p in players if p.action_needed == "promote_to_starter"],
        key=lambda x: x.fp_proj,
        reverse=True,
    )
    remaining_benched = sorted(
        [p for p in players if p.action_needed == "bench_player"],
        key=lambda x: x.fp_proj,
    )
    swaps: list[dict[str, Any]] = []
    for p_in in promoted:
        p_out = next(
            (b for b in remaining_benched if b.current_slot == p_in.optimal_slot),
            None,
        )
        if p_out is None and remaining_benched:
            p_out = remaining_benched[0]
        if p_out is None:
            continue
        remaining_benched.remove(p_out)
        swaps.append(
            {
                "slot": p_in.optimal_slot,
                "player_in": _serialize_player(p_in),
                "player_out": _serialize_player(p_out),
                "points_delta": round(p_in.fp_proj - p_out.fp_proj, 1),
                "reason": p_in.swap_reason,
            }
        )
    return swaps


@app.get("/api/overview")
def get_overview(db: Session = Depends(get_db)) -> dict[str, Any]:
    leagues = db.query(League).order_by(League.league_key).all()
    leagues_out: list[dict[str, Any]] = []

    for lg in leagues:
        players = db.query(RosterPlayer).filter(RosterPlayer.league_key == lg.league_key).all()
        fas = db.query(FreeAgentCandidate).filter(FreeAgentCandidate.league_key == lg.league_key).all()
        matchup = db.query(MatchupSnapshot).filter(MatchupSnapshot.league_key == lg.league_key).first()

        cur_proj = round(sum(p.fp_proj for p in players if p.is_starter_current), 1)
        opt_proj = round(sum(p.fp_proj for p in players if p.is_starter_optimal), 1)
        swaps_count = sum(1 for p in players if p.action_needed == "promote_to_starter")
        injury_alerts = sum(
            1
            for p in players
            if p.is_starter_current and p.status.upper() in ("O", "OUT", "IR", "D", "Q", "BYE")
        )

        leagues_out.append(
            {
                "league_key": lg.league_key,
                "name": lg.name,
                "season": lg.season,
                "current_week": lg.current_week,
                "scoring_type": lg.scoring_type,
                "scoring_label": SCORING_LABELS.get(lg.scoring_type, lg.scoring_type.upper()),
                "num_teams": lg.num_teams,
                "team_key": lg.team_key,
                "team_name": lg.team_name,
                "team_record": lg.team_record,
                "team_standing": lg.team_standing,
                "points_for": lg.points_for,
                "points_against": lg.points_against,
                "faab_balance": lg.faab_balance,
                "execution_mode": lg.execution_mode,
                "is_demo": lg.is_demo,
                "last_synced_at": lg.last_synced_at.isoformat() if lg.last_synced_at else None,
                "current_proj": cur_proj,
                "optimal_proj": opt_proj,
                "net_gain": round(opt_proj - cur_proj, 1),
                "pending_swaps_count": swaps_count,
                "injury_alerts_count": injury_alerts,
                "fa_upgrades_count": len(fas),
                "starter_fa_upgrades_count": sum(1 for f in fas if f.recommendation_type == "starter_upgrade"),
                "matchup": {
                    "week": matchup.week if matchup else lg.current_week,
                    "opponent_team_name": matchup.opponent_team_name if matchup else "Opponent",
                    "opponent_record": matchup.opponent_record if matchup else "0-0-0",
                    "opponent_projected_points": matchup.opponent_projected_points if matchup else 0.0,
                    "win_probability": matchup.win_probability if matchup else 50.0,
                },
            }
        )

    latest_run = (
        db.query(RecommendationRun)
        .order_by(RecommendationRun.created_at.desc())
        .first()
    )
    eff = get_effective_settings(db)
    sched = get_scheduler_status()

    return {
        "leagues": leagues_out,
        "oauth": get_oauth_status(db),
        "scheduler": {
            **sched,
            "daily_sync_time": eff.get("daily_sync_time", "08:00"),
            "timezone": eff.get("timezone", "America/New_York"),
            "dry_run": eff.get("dry_run", True),
        },
        "smtp_configured": bool(eff.get("smtp_username") and eff.get("smtp_app_password")),
        "latest_run": {
            "id": latest_run.id,
            "created_at": latest_run.created_at.isoformat(),
            "trigger_source": latest_run.trigger_source,
            "data_source": latest_run.data_source,
            "leagues_processed": latest_run.leagues_processed,
            "total_swaps_recommended": latest_run.total_swaps_recommended,
            "total_fa_upgrades": latest_run.total_fa_upgrades,
            "lineup_changes_applied": latest_run.lineup_changes_applied,
            "email_sent": latest_run.email_sent,
            "email_subject": latest_run.email_subject,
        }
        if latest_run
        else None,
    }


@app.get("/api/leagues/{league_key}")
def get_league_detail(league_key: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    lg = db.query(League).filter(League.league_key == league_key).first()
    if not lg:
        raise HTTPException(status_code=404, detail=f"League {league_key} not found")

    players = db.query(RosterPlayer).filter(RosterPlayer.league_key == league_key).all()
    fas_raw = (
        db.query(FreeAgentCandidate)
        .filter(FreeAgentCandidate.league_key == league_key)
        .all()
    )
    fas = sorted(
        fas_raw,
        key=lambda f: (
            1 if f.recommendation_type == "starter_upgrade" else 0,
            f.net_starter_gain,
            f.fp_proj,
        ),
        reverse=True,
    )
    matchup = db.query(MatchupSnapshot).filter(MatchupSnapshot.league_key == league_key).first()

    slot_order = {"QB": 1, "RB": 2, "WR": 3, "TE": 4, "W/R/T": 5, "W/R": 5, "Q/W/R/T": 6, "K": 7, "DEF": 8, "BN": 9, "IR": 10}
    players_sorted = sorted(
        players,
        key=lambda p: (slot_order.get(p.current_slot, 9), -p.fp_proj),
    )

    cur_proj = round(sum(p.fp_proj for p in players if p.is_starter_current), 1)
    opt_proj = round(sum(p.fp_proj for p in players if p.is_starter_optimal), 1)
    swaps = _build_swaps_from_roster(players)

    yahoo_xml_preview = build_roster_put_xml(
        week=lg.current_week,
        player_positions=[
            {"player_key": p.player_key, "position": p.optimal_slot}
            for p in players_sorted
        ],
    )

    return {
        "league": {
            "league_key": lg.league_key,
            "name": lg.name,
            "season": lg.season,
            "current_week": lg.current_week,
            "scoring_type": lg.scoring_type,
            "scoring_label": SCORING_LABELS.get(lg.scoring_type, lg.scoring_type.upper()),
            "num_teams": lg.num_teams,
            "roster_slots": json.loads(lg.roster_slots_json or "[]"),
            "team_key": lg.team_key,
            "team_name": lg.team_name,
            "team_record": lg.team_record,
            "team_standing": lg.team_standing,
            "points_for": lg.points_for,
            "points_against": lg.points_against,
            "faab_balance": lg.faab_balance,
            "execution_mode": lg.execution_mode,
            "is_demo": lg.is_demo,
            "last_synced_at": lg.last_synced_at.isoformat() if lg.last_synced_at else None,
            "current_proj": cur_proj,
            "optimal_proj": opt_proj,
            "net_gain": round(opt_proj - cur_proj, 1),
        },
        "roster": [_serialize_player(p) for p in players_sorted],
        "swaps": swaps,
        "free_agents": [
            {
                "player_key": fa.player_key,
                "name": fa.name,
                "team": fa.team,
                "position": fa.position,
                "eligible_positions": json.loads(fa.eligible_positions_json or "[]"),
                "availability_type": fa.availability_type,
                "percent_owned": fa.percent_owned,
                "status": fa.status,
                "bye_week": fa.bye_week,
                "opponent": fa.opponent,
                "yahoo_proj": fa.yahoo_proj,
                "fp_ecr": fa.fp_ecr,
                "fp_pos_rank": fa.fp_pos_rank,
                "fp_proj": fa.fp_proj,
                "fp_tier": fa.fp_tier,
                "ros_ecr": getattr(fa, "ros_ecr", 999) or 999,
                "ros_pos_rank": getattr(fa, "ros_pos_rank", "") or "",
                "recommended_drop_player_key": fa.recommended_drop_player_key,
                "recommended_drop_player_name": fa.recommended_drop_player_name,
                "recommended_drop_player_proj": fa.recommended_drop_player_proj,
                "recommended_drop_player_ros_rank": getattr(fa, "recommended_drop_player_ros_rank", "") or "",
                "recommended_target_slot": fa.recommended_target_slot,
                "net_starter_gain": fa.net_starter_gain,
                "net_bench_gain": fa.net_bench_gain,
                "recommendation_type": fa.recommendation_type,
                "rationale": fa.rationale,
            }
            for fa in fas
        ],
        "matchup": {
            "week": matchup.week if matchup else lg.current_week,
            "my_projected_points": cur_proj,
            "my_optimal_projected_points": opt_proj,
            "opponent_team_name": matchup.opponent_team_name if matchup else "Opponent",
            "opponent_manager": matchup.opponent_manager if matchup else "",
            "opponent_record": matchup.opponent_record if matchup else "0-0-0",
            "opponent_projected_points": matchup.opponent_projected_points if matchup else 0.0,
            "win_probability": matchup.win_probability if matchup else 50.0,
            "schedule": json.loads(matchup.schedule_json or "[]") if matchup else [],
        },
        "yahoo_xml_preview": yahoo_xml_preview,
    }


_FP_INDEX_MEMORY_CACHE: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}


@app.get("/api/leagues/{league_key}/teams")
async def get_league_teams(league_key: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Fetches all teams in the specified Yahoo league, evaluates each team's active starting lineup
    and bench against FantasyPros Weekly + ROS rankings, and flags opponent lineup issues (BYE/Out starters,
    points left on bench, and ROS power rating).
    """
    import time

    lg = db.query(League).filter(League.league_key == league_key).first()
    if not lg:
        raise HTTPException(status_code=404, detail=f"League {league_key} not found")

    matchup = db.query(MatchupSnapshot).filter(MatchupSnapshot.league_key == league_key).first()
    opp_name = (matchup.opponent_team_name if matchup else "").strip().lower()
    roster_slots = json.loads(lg.roster_slots_json or '["QB","RB","RB","WR","WR","TE","W/R/T","K","DEF","BN","BN","BN","BN","BN","BN"]')
    slot_order = {"QB": 1, "RB": 2, "WR": 3, "TE": 4, "W/R/T": 5, "W/R": 5, "Q/W/R/T": 6, "K": 7, "DEF": 8, "BN": 9, "IR": 10}

    now = time.time()
    cached = _FP_INDEX_MEMORY_CACHE.get(lg.scoring_type)
    if cached and (now - cached[0]) < 900:
        fp_index = cached[1]
    else:
        fp_index = await fetch_fantasypros_weekly_index(lg.scoring_type, attempt_live=True)
        _FP_INDEX_MEMORY_CACHE[lg.scoring_type] = (now, fp_index)

    yclient = await get_yahoo_client(db)
    raw_teams = await yclient.fetch_league_teams_overview(league_key, lg.current_week)

    teams_analyzed: list[dict[str, Any]] = []
    for t in raw_teams:
        enriched = [_enrich_player_with_fp(p, fp_index) for p in t.get("roster", [])]
        opt = solve_optimal_lineup(enriched, roster_slots)
        players_sorted = sorted(
            opt["players"],
            key=lambda p: (slot_order.get(p.get("current_slot", "BN"), 9), -float(p.get("fp_proj", 0.0))),
        )
        starters = [p for p in players_sorted if p.get("is_starter_current")]
        inactive_starters = [
            p for p in starters if str(p.get("status", "Healthy")).upper() in ("BYE", "O", "OUT", "IR", "D", "SUSP")
        ]
        questionable_starters = [p for p in starters if str(p.get("status", "Healthy")).upper() == "Q"]
        top100_ros_count = sum(1 for p in players_sorted if int(p.get("ros_ecr", 999)) <= 100)
        cur_proj = float(opt["current_projected_total"])
        opt_proj = float(opt["optimal_projected_total"])
        bench_gain = float(opt["net_gain"])

        if inactive_starters:
            names = ", ".join(f"{p['name']} ({p['status']})" for p in inactive_starters[:2])
            status_severity = "alert"
            status_summary = f"{len(inactive_starters)} Inactive Starter{'s' if len(inactive_starters) > 1 else ''}: {names}"
        elif bench_gain >= 3.0:
            status_severity = "warning"
            status_summary = f"Suboptimal Lineup (+{bench_gain:.1f} pts on bench)"
        elif questionable_starters:
            status_severity = "warning"
            status_summary = f"{len(questionable_starters)} Questionable Starter{'s' if len(questionable_starters) > 1 else ''}"
        else:
            status_severity = "optimal"
            status_summary = "Lineup Ready & Optimal"

        teams_analyzed.append(
            {
                "team_key": t["team_key"],
                "team_name": t["team_name"],
                "manager_name": t["manager_name"],
                "is_my_team": t["is_my_team"],
                "is_current_opponent": bool(opp_name and t["team_name"].strip().lower() == opp_name),
                "rank": t["rank"],
                "record": t["record"],
                "streak": t["streak"],
                "points_for": t["points_for"],
                "points_against": t["points_against"],
                "waiver_priority": t["waiver_priority"],
                "number_of_moves": t["number_of_moves"],
                "faab_balance": t["faab_balance"],
                "current_proj": cur_proj,
                "optimal_proj": opt_proj,
                "points_left_on_bench": bench_gain,
                "inactive_starters_count": len(inactive_starters),
                "questionable_starters_count": len(questionable_starters),
                "top100_ros_count": top100_ros_count,
                "status_severity": status_severity,
                "status_summary": status_summary,
                "swaps_count": len(opt["swaps"]),
                "swaps": opt["swaps"],
                "roster": players_sorted,
            }
        )

    return {
        "league_key": league_key,
        "league_name": lg.name,
        "current_week": lg.current_week,
        "teams": teams_analyzed,
    }


@app.post("/api/leagues/{league_key}/execution-mode")
def update_league_execution_mode(
    league_key: str,
    payload: ExecutionModePayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if payload.execution_mode not in ("advisory", "auto_lineup"):
        raise HTTPException(status_code=400, detail="execution_mode must be 'advisory' or 'auto_lineup'")
    lg = db.query(League).filter(League.league_key == league_key).first()
    if not lg:
        raise HTTPException(status_code=404, detail="League not found")
    lg.execution_mode = payload.execution_mode
    db.commit()
    return {"league_key": league_key, "execution_mode": lg.execution_mode}


@app.post("/api/leagues/{league_key}/apply-lineup")
async def apply_league_lineup(league_key: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return await apply_optimal_lineup_for_league(db, league_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/sync")
async def trigger_sync(
    payload: SyncRequestPayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await run_daily_autopilot_pipeline(
            db=db,
            trigger_source="manual",
            send_email=payload.send_email,
            attempt_live_fp=payload.attempt_live_fp,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/runs")
def list_runs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    runs = (
        db.query(RecommendationRun)
        .order_by(RecommendationRun.created_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "trigger_source": r.trigger_source,
            "data_source": r.data_source,
            "leagues_processed": r.leagues_processed,
            "total_swaps_recommended": r.total_swaps_recommended,
            "total_fa_upgrades": r.total_fa_upgrades,
            "lineup_changes_applied": r.lineup_changes_applied,
            "email_sent": r.email_sent,
            "email_recipient": r.email_recipient,
            "email_subject": r.email_subject,
        }
        for r in runs
    ]


@app.get("/api/runs/latest/email-preview", response_class=HTMLResponse)
def get_latest_email_preview(db: Session = Depends(get_db)) -> HTMLResponse:
    latest = (
        db.query(RecommendationRun)
        .order_by(RecommendationRun.created_at.desc())
        .first()
    )
    if not latest or not latest.email_html:
        return HTMLResponse("<html><body><p>No email digest generated yet.</p></body></html>")
    return HTMLResponse(latest.email_html)


@app.post("/api/notifications/send-email")
def send_digest_email_now(
    payload: SendEmailPayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    latest = (
        db.query(RecommendationRun)
        .order_by(RecommendationRun.created_at.desc())
        .first()
    )
    if not latest or not latest.email_html:
        raise HTTPException(status_code=400, detail="Run a sync first to generate the email digest.")

    res = send_smtp_email(
        db=db,
        subject=latest.email_subject,
        html_body=latest.email_html,
        override_recipient=payload.recipient,
    )
    if res.get("sent"):
        latest.email_sent = True
        latest.email_recipient = str(res.get("recipient", ""))
        db.commit()
    return res


@app.get("/api/settings")
def read_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    eff = get_effective_settings(db)
    masked = dict(eff)
    if masked.get("yahoo_client_secret"):
        masked["yahoo_client_secret"] = "••••••••••••"
    if masked.get("smtp_app_password"):
        masked["smtp_app_password"] = "••••••••••••"
    if masked.get("yahoo_cookie"):
        masked["yahoo_cookie"] = "••••••••••••"
    masked["has_yahoo_secret"] = bool(eff.get("yahoo_client_secret"))
    masked["has_smtp_password"] = bool(eff.get("smtp_app_password"))
    masked["has_yahoo_cookie"] = bool(eff.get("yahoo_cookie"))
    return masked


@app.put("/api/settings")
def save_settings(payload: SettingsUpdatePayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    updates = payload.model_dump(exclude_none=True)
    if "dry_run" in updates:
        updates["dry_run"] = "true" if updates["dry_run"] else "false"
    update_settings(db, updates)
    configure_daily_scheduler()
    return read_settings(db)


@app.get("/api/auth/yahoo/login")
async def yahoo_login_url(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        url = await build_yahoo_authorize_url(db)
        return {"authorize_url": url}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/auth/yahoo/callback")
async def yahoo_oauth_callback(
    code: str = Query(...),
    db: Session = Depends(get_db),
):
    await exchange_code_for_token(db, code)
    await run_daily_autopilot_pipeline(db, trigger_source="oauth_callback", send_email=False)
    return RedirectResponse(url="/")


@app.post("/api/auth/yahoo/code")
async def yahoo_exchange_code_manual(
    payload: YahooCodePayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        token = await exchange_code_for_token(db, payload.code)
        sync_res = await run_daily_autopilot_pipeline(db, trigger_source="oauth_manual", send_email=False)
        return {
            "connected": True,
            "yahoo_guid": token.yahoo_guid,
            "sync_result": sync_res,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class YahooCookiePayload(BaseModel):
    cookie_or_curl: str


@app.post("/api/auth/yahoo/cookie")
async def yahoo_connect_cookie(
    payload: YahooCookiePayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        save_yahoo_cookie(db, payload.cookie_or_curl)
        sync_res = await run_daily_autopilot_pipeline(db, trigger_source="cookie_connect", send_email=False)
        return {
            "connected": True,
            "auth_mode": "cookie",
            "sync_result": sync_res,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# Serve compiled frontend SPA in production / Docker if frontend/dist exists
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
