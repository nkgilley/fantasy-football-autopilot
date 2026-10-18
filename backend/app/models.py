from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String(50), default="yahoo")
    access_token: Mapped[str] = mapped_column(Text, default="")
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    token_type: Mapped[str] = mapped_column(String(50), default="bearer")
    expires_at: Mapped[float] = mapped_column(Float, default=0.0)
    yahoo_guid: Mapped[str] = mapped_column(String(120), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class League(Base):
    __tablename__ = "leagues"

    league_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    league_id: Mapped[str] = mapped_column(String(32), default="")
    name: Mapped[str] = mapped_column(String(200))
    season: Mapped[int] = mapped_column(Integer, default=2026)
    current_week: Mapped[int] = mapped_column(Integer, default=7)
    scoring_type: Mapped[str] = mapped_column(String(32), default="half_ppr")  # std | half_ppr | ppr
    num_teams: Mapped[int] = mapped_column(Integer, default=12)
    roster_slots_json: Mapped[str] = mapped_column(
        Text,
        default='["QB","RB","RB","WR","WR","TE","W/R/T","K","DEF","BN","BN","BN","BN","BN","BN","IR"]',
    )
    team_key: Mapped[str] = mapped_column(String(64), default="")
    team_name: Mapped[str] = mapped_column(String(200), default="")
    team_record: Mapped[str] = mapped_column(String(32), default="0-0-0")
    team_standing: Mapped[int] = mapped_column(Integer, default=1)
    points_for: Mapped[float] = mapped_column(Float, default=0.0)
    points_against: Mapped[float] = mapped_column(Float, default=0.0)
    faab_balance: Mapped[int] = mapped_column(Integer, default=100)
    execution_mode: Mapped[str] = mapped_column(String(32), default="advisory")  # advisory | auto_lineup
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MatchupSnapshot(Base):
    __tablename__ = "matchup_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_key: Mapped[str] = mapped_column(String(64), ForeignKey("leagues.league_key", ondelete="CASCADE"), index=True)
    week: Mapped[int] = mapped_column(Integer, default=7)
    my_projected_points: Mapped[float] = mapped_column(Float, default=0.0)
    my_optimal_projected_points: Mapped[float] = mapped_column(Float, default=0.0)
    opponent_team_name: Mapped[str] = mapped_column(String(200), default="")
    opponent_manager: Mapped[str] = mapped_column(String(120), default="")
    opponent_record: Mapped[str] = mapped_column(String(32), default="0-0-0")
    opponent_projected_points: Mapped[float] = mapped_column(Float, default=0.0)
    win_probability: Mapped[float] = mapped_column(Float, default=50.0)
    schedule_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RosterPlayer(Base):
    __tablename__ = "roster_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_key: Mapped[str] = mapped_column(String(64), ForeignKey("leagues.league_key", ondelete="CASCADE"), index=True)
    player_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    team: Mapped[str] = mapped_column(String(16), default="")
    position: Mapped[str] = mapped_column(String(16))  # QB, RB, WR, TE, K, DEF
    eligible_positions_json: Mapped[str] = mapped_column(Text, default="[]")
    current_slot: Mapped[str] = mapped_column(String(16))  # QB, RB, WR, TE, W/R/T, K, DEF, BN, IR
    optimal_slot: Mapped[str] = mapped_column(String(16), default="BN")
    status: Mapped[str] = mapped_column(String(32), default="Healthy")  # Healthy, Q, D, O, IR, BYE
    injury_note: Mapped[str] = mapped_column(String(255), default="")
    bye_week: Mapped[int] = mapped_column(Integer, default=0)
    opponent: Mapped[str] = mapped_column(String(32), default="")
    game_time: Mapped[str] = mapped_column(String(64), default="")
    yahoo_proj: Mapped[float] = mapped_column(Float, default=0.0)
    fp_ecr: Mapped[int] = mapped_column(Integer, default=999)
    fp_pos_rank: Mapped[str] = mapped_column(String(32), default="")
    fp_proj: Mapped[float] = mapped_column(Float, default=0.0)
    fp_tier: Mapped[int] = mapped_column(Integer, default=5)
    ros_ecr: Mapped[int] = mapped_column(Integer, default=999)
    ros_pos_rank: Mapped[str] = mapped_column(String(32), default="")
    is_starter_current: Mapped[bool] = mapped_column(Boolean, default=False)
    is_starter_optimal: Mapped[bool] = mapped_column(Boolean, default=False)
    action_needed: Mapped[str] = mapped_column(String(32), default="keep")  # keep, promote_to_starter, bench_player
    swap_reason: Mapped[str] = mapped_column(Text, default="")


class FreeAgentCandidate(Base):
    __tablename__ = "free_agent_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_key: Mapped[str] = mapped_column(String(64), ForeignKey("leagues.league_key", ondelete="CASCADE"), index=True)
    player_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    team: Mapped[str] = mapped_column(String(16), default="")
    position: Mapped[str] = mapped_column(String(16))
    eligible_positions_json: Mapped[str] = mapped_column(Text, default="[]")
    availability_type: Mapped[str] = mapped_column(String(16), default="FA")  # FA | W (Waivers)
    waiver_clear_date: Mapped[str] = mapped_column(String(32), default="")
    percent_owned: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="Healthy")
    bye_week: Mapped[int] = mapped_column(Integer, default=0)
    opponent: Mapped[str] = mapped_column(String(32), default="")
    yahoo_proj: Mapped[float] = mapped_column(Float, default=0.0)
    fp_ecr: Mapped[int] = mapped_column(Integer, default=999)
    fp_pos_rank: Mapped[str] = mapped_column(String(32), default="")
    fp_proj: Mapped[float] = mapped_column(Float, default=0.0)
    fp_tier: Mapped[int] = mapped_column(Integer, default=5)
    ros_ecr: Mapped[int] = mapped_column(Integer, default=999)
    ros_pos_rank: Mapped[str] = mapped_column(String(32), default="")
    recommended_drop_player_key: Mapped[str] = mapped_column(String(64), default="")
    recommended_drop_player_name: Mapped[str] = mapped_column(String(200), default="")
    recommended_drop_player_proj: Mapped[float] = mapped_column(Float, default=0.0)
    recommended_drop_player_ros_rank: Mapped[str] = mapped_column(String(32), default="")
    recommended_target_slot: Mapped[str] = mapped_column(String(16), default="BN")
    net_starter_gain: Mapped[float] = mapped_column(Float, default=0.0)
    net_bench_gain: Mapped[float] = mapped_column(Float, default=0.0)
    recommendation_type: Mapped[str] = mapped_column(String(32), default="bench_upgrade")  # starter_upgrade | bench_upgrade | watch
    rationale: Mapped[str] = mapped_column(Text, default="")


class RecommendationRun(Base):
    __tablename__ = "recommendation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    trigger_source: Mapped[str] = mapped_column(String(32), default="manual")  # scheduled | manual | startup
    data_source: Mapped[str] = mapped_column(String(32), default="live")  # yahoo_live | demo
    leagues_processed: Mapped[int] = mapped_column(Integer, default=0)
    total_swaps_recommended: Mapped[int] = mapped_column(Integer, default=0)
    total_fa_upgrades: Mapped[int] = mapped_column(Integer, default=0)
    lineup_changes_applied: Mapped[int] = mapped_column(Integer, default=0)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    email_recipient: Mapped[str] = mapped_column(String(200), default="")
    email_subject: Mapped[str] = mapped_column(String(255), default="")
    email_html: Mapped[str] = mapped_column(Text, default="")
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
