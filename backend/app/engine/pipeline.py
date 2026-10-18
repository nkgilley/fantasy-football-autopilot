from datetime import datetime, timezone
import json
import logging
from typing import Any
from sqlalchemy.orm import Session

from app.engine.demo_seed import get_demo_leagues_raw
from app.engine.optimizer import analyze_free_agent_upgrades, solve_optimal_lineup
from app.fantasypros.matcher import match_player_to_fp
from app.fantasypros.scraper import fetch_fantasypros_weekly_index
from app.models import (
    FreeAgentCandidate,
    League,
    MatchupSnapshot,
    RecommendationRun,
    RosterPlayer,
)
from app.notifications.email import render_daily_digest_email, send_smtp_email
from app.settings_store import get_effective_settings
from app.yahoo.auth import get_oauth_status
from app.yahoo.client import get_yahoo_client
from app.yahoo.writer import apply_yahoo_lineup_changes

logger = logging.getLogger(__name__)

SCORING_LABELS = {
    "std": "Standard (Non-PPR)",
    "half_ppr": "Half-PPR (0.5)",
    "ppr": "Full PPR (1.0)",
}


def _enrich_player_with_fp(
    raw_player: dict[str, Any],
    fp_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    matched = match_player_to_fp(
        raw_player.get("name", ""),
        raw_player.get("position", ""),
        raw_player.get("team", ""),
        fp_index,
    )
    status = str(raw_player.get("status", "Healthy"))
    is_inactive = status.upper() in ("O", "OUT", "IR", "BYE", "SUSP")

    from app.fantasypros.matcher import normalize_team

    norm_team = normalize_team(raw_player.get("team", ""))
    team_game = fp_index.get("__team_games__", {}).get(norm_team, {})

    if matched:
        fp_proj = 0.0 if is_inactive else float(matched.get("proj", 0.0))
        fp_ecr = int(matched.get("ecr", 999))
        fp_pos_rank = str(matched.get("pos_rank", f"{raw_player.get('position', 'P')}{fp_ecr}"))
        fp_tier = int(matched.get("tier", 5))
        ros_ecr = int(matched.get("ros_ecr", 999))
        ros_pos_rank = str(matched.get("ros_pos_rank") or fp_pos_rank)
        opp = str(matched.get("opp") or team_game.get("opp") or raw_player.get("opponent") or "")
        game_time = str(matched.get("game_time") or team_game.get("game_time") or raw_player.get("game_time") or "")
        fp_locked = bool(matched.get("is_locked") or team_game.get("is_locked"))
    else:
        fp_proj = 0.0 if is_inactive else float(raw_player.get("yahoo_proj", 8.0))
        fp_ecr = 150
        fp_pos_rank = f"{raw_player.get('position', '')}--"
        fp_tier = 5
        ros_ecr = 450
        ros_pos_rank = f"{raw_player.get('position', '')}--"
        opp = str(team_game.get("opp") or raw_player.get("opponent") or "")
        game_time = str(team_game.get("game_time") or raw_player.get("game_time") or "")
        fp_locked = bool(team_game.get("is_locked"))

    yahoo_locked = raw_player.get("is_editable") is False
    is_locked = bool(fp_locked or yahoo_locked)
    if is_locked and "Locked" not in game_time:
        game_time = f"{game_time} • Played (Locked)" if game_time else "Played (Locked)"

    enriched = dict(raw_player)
    enriched["fp_ecr"] = fp_ecr
    enriched["fp_pos_rank"] = fp_pos_rank
    enriched["fp_proj"] = fp_proj
    enriched["fp_tier"] = fp_tier
    enriched["ros_ecr"] = ros_ecr
    enriched["ros_pos_rank"] = ros_pos_rank
    enriched["opponent"] = "BYE" if status.upper() == "BYE" else opp
    enriched["game_time"] = "" if status.upper() == "BYE" else game_time
    enriched["is_locked"] = is_locked
    enriched["yahoo_proj"] = round(fp_proj * 0.96, 1) if fp_proj > 0 else 0.0
    return enriched


async def run_daily_autopilot_pipeline(
    db: Session,
    trigger_source: str = "manual",
    send_email: bool = False,
    attempt_live_fp: bool = True,
) -> dict[str, Any]:
    """
    Executes the full multi-league sync, FantasyPros weekly ECR matching,
    lineup & waiver optimization, optional auto-lineup execution, and email digest generation.
    """
    eff_settings = get_effective_settings(db)
    oauth_state = get_oauth_status(db)

    raw_leagues: list[dict[str, Any]] = []
    data_source = "demo"

    if oauth_state["connected"]:
        try:
            yclient = await get_yahoo_client(db)
            discovered = await yclient.fetch_user_nfl_leagues()
            for lg_meta in discovered:
                week = int(lg_meta["current_week"])
                roster = await yclient.fetch_team_roster(lg_meta["team_key"], week)
                matchup = await yclient.fetch_team_matchups(lg_meta["team_key"], week)
                free_agents = await yclient.fetch_available_free_agents(lg_meta["league_key"], week)
                lg_meta["roster"] = roster
                lg_meta["matchup"] = matchup
                lg_meta["free_agents"] = free_agents
                lg_meta["is_demo"] = False
                raw_leagues.append(lg_meta)
            data_source = "yahoo_live"
            # Remove demo leagues once real Yahoo leagues are synced
            db.query(League).filter(League.is_demo == True).delete()  # noqa: E712
            db.commit()
        except PermissionError as exc:
            raise RuntimeError(str(exc))
        except Exception as exc:
            logger.error("Yahoo live sync failed: %s", exc)
            if trigger_source != "startup":
                raise RuntimeError(f"Yahoo Fantasy API sync failed: {exc}")

    if not raw_leagues and not oauth_state["connected"]:
        raw_leagues = get_demo_leagues_raw()
        data_source = "demo"

    # Cache FantasyPros weekly indices per scoring format so we only scrape once per scoring type
    fp_cache: dict[str, dict[str, dict[str, Any]]] = {}

    email_leagues_payload: list[dict[str, Any]] = []
    total_swaps_count = 0
    total_fa_count = 0
    lineup_changes_applied = 0

    for raw_lg in raw_leagues:
        lkey = raw_lg["league_key"]
        scoring_type = raw_lg.get("scoring_type", "half_ppr")
        if scoring_type not in fp_cache:
            fp_cache[scoring_type] = await fetch_fantasypros_weekly_index(
                scoring_type=scoring_type,
                attempt_live=attempt_live_fp,
            )
        fp_index = fp_cache[scoring_type]

        # Upsert League record while preserving user-chosen execution_mode
        existing_lg = db.query(League).filter(League.league_key == lkey).first()
        exec_mode = (
            existing_lg.execution_mode
            if existing_lg
            else eff_settings.get("default_execution_mode", "advisory")
        )

        roster_slots = raw_lg.get("roster_slots") or [
            "QB", "RB", "RB", "WR", "WR", "TE", "W/R/T", "K", "DEF",
            "BN", "BN", "BN", "BN", "BN", "BN", "IR",
        ]

        if not existing_lg:
            existing_lg = League(league_key=lkey, name=raw_lg["name"])
            db.add(existing_lg)

        existing_lg.league_id = str(raw_lg.get("league_id", ""))
        existing_lg.name = raw_lg["name"]
        existing_lg.season = int(raw_lg.get("season", 2026))
        existing_lg.current_week = int(raw_lg.get("current_week", 7))
        existing_lg.scoring_type = scoring_type
        existing_lg.num_teams = int(raw_lg.get("num_teams", 12))
        existing_lg.roster_slots_json = json.dumps(roster_slots)
        existing_lg.team_key = raw_lg.get("team_key", "")
        existing_lg.team_name = raw_lg.get("team_name", "My Team")
        existing_lg.team_record = raw_lg.get("team_record", "0-0-0")
        existing_lg.team_standing = int(raw_lg.get("team_standing", 1))
        existing_lg.points_for = float(raw_lg.get("points_for", 0.0))
        existing_lg.points_against = float(raw_lg.get("points_against", 0.0))
        existing_lg.faab_balance = int(raw_lg.get("faab_balance", 100))
        existing_lg.execution_mode = exec_mode
        existing_lg.is_demo = bool(raw_lg.get("is_demo", False))
        existing_lg.last_synced_at = datetime.now(timezone.utc)
        db.flush()

        # Enrich roster & free agents with FantasyPros weekly ECR & projections
        enriched_roster = [_enrich_player_with_fp(p, fp_index) for p in raw_lg.get("roster", [])]
        enriched_fas = [_enrich_player_with_fp(fa, fp_index) for fa in raw_lg.get("free_agents", [])]

        # Run slot-constrained lineup optimizer & free agent upgrade analyzer
        opt_result = solve_optimal_lineup(enriched_roster, roster_slots)
        fa_upgrades = analyze_free_agent_upgrades(opt_result["players"], enriched_fas, roster_slots)

        swaps = opt_result["swaps"]
        total_swaps_count += len(swaps)
        total_fa_count += len(fa_upgrades)

        # If league is configured for auto_lineup and has swaps, execute (or dry-run)
        if exec_mode == "auto_lineup" and swaps:
            pos_payload = [
                {"player_key": p["player_key"], "position": p["optimal_slot"]}
                for p in opt_result["players"]
            ]
            await apply_yahoo_lineup_changes(
                db=db,
                team_key=existing_lg.team_key,
                week=existing_lg.current_week,
                player_positions=pos_payload,
                dry_run=bool(eff_settings.get("dry_run", True)),
                is_demo=existing_lg.is_demo,
            )
            lineup_changes_applied += len(swaps)

        # Replace RosterPlayer rows for this league
        db.query(RosterPlayer).filter(RosterPlayer.league_key == lkey).delete()
        for p in opt_result["players"]:
            db.add(
                RosterPlayer(
                    league_key=lkey,
                    player_key=p["player_key"],
                    name=p["name"],
                    team=p.get("team", ""),
                    position=p["position"],
                    eligible_positions_json=json.dumps(p.get("eligible_positions", [p["position"]])),
                    current_slot=p.get("current_slot", "BN"),
                    optimal_slot=p.get("optimal_slot", "BN"),
                    status=p.get("status", "Healthy"),
                    injury_note=p.get("injury_note", ""),
                    bye_week=int(p.get("bye_week", 0)),
                    opponent=p.get("opponent", ""),
                    game_time=p.get("game_time", ""),
                    yahoo_proj=float(p.get("yahoo_proj", 0.0)),
                    fp_ecr=int(p.get("fp_ecr", 999)),
                    fp_pos_rank=p.get("fp_pos_rank", ""),
                    fp_proj=float(p.get("fp_proj", 0.0)),
                    fp_tier=int(p.get("fp_tier", 5)),
                    ros_ecr=int(p.get("ros_ecr", 999)),
                    ros_pos_rank=p.get("ros_pos_rank", ""),
                    is_starter_current=bool(p.get("is_starter_current", False)),
                    is_starter_optimal=bool(p.get("is_starter_optimal", False)),
                    action_needed=p.get("action_needed", "keep"),
                    swap_reason=p.get("swap_reason", ""),
                )
            )

        # Replace FreeAgentCandidate rows for this league
        db.query(FreeAgentCandidate).filter(FreeAgentCandidate.league_key == lkey).delete()
        for fa in fa_upgrades:
            db.add(
                FreeAgentCandidate(
                    league_key=lkey,
                    player_key=fa["player_key"],
                    name=fa["name"],
                    team=fa.get("team", ""),
                    position=fa["position"],
                    eligible_positions_json=json.dumps(fa.get("eligible_positions", [fa["position"]])),
                    availability_type=fa.get("availability_type", "FA"),
                    percent_owned=float(fa.get("percent_owned", 0.0)),
                    status=fa.get("status", "Healthy"),
                    bye_week=int(fa.get("bye_week", 0)),
                    opponent=fa.get("opponent", ""),
                    yahoo_proj=float(fa.get("yahoo_proj", 0.0)),
                    fp_ecr=int(fa.get("fp_ecr", 999)),
                    fp_pos_rank=fa.get("fp_pos_rank", ""),
                    fp_proj=float(fa.get("fp_proj", 0.0)),
                    fp_tier=int(fa.get("fp_tier", 5)),
                    ros_ecr=int(fa.get("ros_ecr", 999)),
                    ros_pos_rank=fa.get("ros_pos_rank", ""),
                    recommended_drop_player_key=fa.get("recommended_drop_player_key", ""),
                    recommended_drop_player_name=fa.get("recommended_drop_player_name", ""),
                    recommended_drop_player_proj=float(fa.get("recommended_drop_player_proj", 0.0)),
                    recommended_drop_player_ros_rank=fa.get("recommended_drop_player_ros_rank", ""),
                    recommended_target_slot=fa.get("recommended_target_slot", "BN"),
                    net_starter_gain=float(fa.get("net_starter_gain", 0.0)),
                    net_bench_gain=float(fa.get("net_bench_gain", 0.0)),
                    recommendation_type=fa.get("recommendation_type", "bench_upgrade"),
                    rationale=fa.get("rationale", ""),
                )
            )

        # Replace MatchupSnapshot for this league
        raw_matchup = raw_lg.get("matchup", {})
        opp_proj = float(raw_matchup.get("opponent_projected_points", 115.0))
        opt_proj = float(opt_result["optimal_projected_total"])
        cur_proj = float(opt_result["current_projected_total"])
        # Estimate win probability based on point differential vs opponent
        diff = opt_proj - opp_proj
        win_prob = round(min(95.0, max(5.0, 50.0 + diff * 1.8)), 1)

        db.query(MatchupSnapshot).filter(MatchupSnapshot.league_key == lkey).delete()
        db.add(
            MatchupSnapshot(
                league_key=lkey,
                week=existing_lg.current_week,
                my_projected_points=cur_proj,
                my_optimal_projected_points=opt_proj,
                opponent_team_name=raw_matchup.get("opponent_team_name", "Opponent"),
                opponent_manager=raw_matchup.get("opponent_manager", ""),
                opponent_record=raw_matchup.get("opponent_record", "0-0-0"),
                opponent_projected_points=opp_proj,
                win_probability=win_prob,
                schedule_json=json.dumps(raw_matchup.get("schedule", [])),
            )
        )

        email_leagues_payload.append(
            {
                "league_key": lkey,
                "name": existing_lg.name,
                "scoring_label": SCORING_LABELS.get(scoring_type, scoring_type.upper()),
                "current_week": existing_lg.current_week,
                "team_name": existing_lg.team_name,
                "team_record": existing_lg.team_record,
                "team_standing": existing_lg.team_standing,
                "num_teams": existing_lg.num_teams,
                "execution_mode": existing_lg.execution_mode,
                "current_proj": cur_proj,
                "optimal_proj": opt_proj,
                "net_gain": opt_result["net_gain"],
                "matchup": {
                    "opponent_team_name": raw_matchup.get("opponent_team_name", "Opponent"),
                    "opponent_record": raw_matchup.get("opponent_record", "0-0-0"),
                    "opponent_projected_points": opp_proj,
                },
                "swaps": swaps,
                "fa_upgrades": fa_upgrades,
            }
        )

    subject, email_html = render_daily_digest_email(email_leagues_payload)
    email_result = {"sent": False, "recipient": eff_settings.get("email_to", "")}
    if send_email:
        email_result = send_smtp_email(db, subject, email_html)

    run_record = RecommendationRun(
        trigger_source=trigger_source,
        data_source=data_source,
        leagues_processed=len(raw_leagues),
        total_swaps_recommended=total_swaps_count,
        total_fa_upgrades=total_fa_count,
        lineup_changes_applied=lineup_changes_applied,
        email_sent=bool(email_result.get("sent", False)),
        email_recipient=str(email_result.get("recipient", "")),
        email_subject=subject,
        email_html=email_html,
        summary_json=json.dumps(
            {
                "leagues": [
                    {
                        "league_key": lg["league_key"],
                        "name": lg["name"],
                        "swaps": len(lg["swaps"]),
                        "fa_upgrades": len(lg["fa_upgrades"]),
                        "net_gain": lg["net_gain"],
                    }
                    for lg in email_leagues_payload
                ],
                "email_result": email_result,
            }
        ),
    )
    db.add(run_record)
    db.commit()
    db.refresh(run_record)

    return {
        "run_id": run_record.id,
        "created_at": run_record.created_at.isoformat(),
        "data_source": data_source,
        "leagues_processed": run_record.leagues_processed,
        "total_swaps_recommended": run_record.total_swaps_recommended,
        "total_fa_upgrades": run_record.total_fa_upgrades,
        "lineup_changes_applied": run_record.lineup_changes_applied,
        "email_sent": run_record.email_sent,
        "email_result": email_result,
        "email_subject": subject,
    }


async def apply_optimal_lineup_for_league(
    db: Session,
    league_key: str,
) -> dict[str, Any]:
    """
    Applies the currently recommended optimal starting lineup for a specific league.
    Calls Yahoo's PUT /team/{team_key}/roster endpoint (or simulates if dry_run/demo)
    and updates the local roster state so the UI reflects the applied changes.
    """
    league = db.query(League).filter(League.league_key == league_key).first()
    if not league:
        raise ValueError(f"League {league_key} not found.")

    eff_settings = get_effective_settings(db)
    players = db.query(RosterPlayer).filter(RosterPlayer.league_key == league_key).all()
    if not players:
        raise ValueError(f"No roster found for league {league_key}.")

    player_positions = [
        {"player_key": p.player_key, "position": p.optimal_slot}
        for p in players
    ]
    swaps_applied = sum(1 for p in players if p.action_needed == "promote_to_starter")

    write_result = await apply_yahoo_lineup_changes(
        db=db,
        team_key=league.team_key,
        week=league.current_week,
        player_positions=player_positions,
        dry_run=bool(eff_settings.get("dry_run", True)),
        is_demo=league.is_demo,
    )

    # Update local RosterPlayer slots to match optimal slots
    for p in players:
        p.current_slot = p.optimal_slot
        p.is_starter_current = p.is_starter_optimal
        p.action_needed = "keep"
        p.swap_reason = ""

    matchup = db.query(MatchupSnapshot).filter(MatchupSnapshot.league_key == league_key).first()
    if matchup:
        matchup.my_projected_points = matchup.my_optimal_projected_points

    db.commit()

    return {
        "league_key": league_key,
        "league_name": league.name,
        "swaps_applied": swaps_applied,
        "yahoo_response": write_result,
    }
