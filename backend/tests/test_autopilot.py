import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.engine.optimizer import analyze_free_agent_upgrades, solve_optimal_lineup
from app.engine.pipeline import apply_optimal_lineup_for_league, run_daily_autopilot_pipeline
from app.fantasypros.matcher import match_player_to_fp, normalize_player_name
from app.fantasypros.scraper import build_baseline_fp_index, parse_fantasypros_html
from app.yahoo.writer import build_roster_put_xml


def test_player_normalization_and_fp_matching():
    fp_index = build_baseline_fp_index("half_ppr")

    # Suffix and punctuation normalization
    assert normalize_player_name("Brian Thomas Jr.", "WR", "JAX") == "brian thomas"
    assert normalize_player_name("Kenneth Walker III", "RB", "SEA") == "kenneth walker"
    assert normalize_player_name("New York Jets", "DEF", "NYJ") == "def_nyj"

    m_btj = match_player_to_fp("Brian Thomas Jr.", "WR", "JAC", fp_index)
    assert m_btj is not None
    assert m_btj["pos_rank"] == "WR18"
    assert m_btj["proj"] > 12.0

    m_def = match_player_to_fp("Denver Broncos", "DEF", "DEN", fp_index)
    assert m_def is not None
    assert m_def["pos_rank"] == "DST2"


def test_parse_fantasypros_embedded_ecr_json():
    sample_html = """
    <html><head><script>
    var ecrData = {"players": [
        {"player_name": "Josh Allen", "player_team_id": "BUF", "rank_ecr": 1, "pos_rank": "QB1", "tier": 1, "r2p_pts": "24.8", "player_opponent": "vs TEN"},
        {"player_name": "Jayden Daniels", "player_team_id": "WAS", "rank_ecr": 2, "pos_rank": "QB2", "tier": 1, "r2p_pts": "23.1", "player_opponent": "vs CAR"}
    ]};
    </script></head><body></body></html>
    """
    parsed = parse_fantasypros_html(sample_html, "QB")
    assert len(parsed) == 2
    assert parsed[0]["name"] == "Josh Allen"
    assert parsed[0]["proj"] == 24.8
    assert parsed[1]["team"] == "WAS"


def test_lineup_optimizer_handles_bye_and_flex_upgrades():
    roster_slots = ["QB", "RB", "WR", "TE", "W/R/T", "BN", "BN"]
    players = [
        {"player_key": "p1", "name": "Josh Allen", "position": "QB", "eligible_positions": ["QB"], "current_slot": "QB", "status": "Healthy", "fp_proj": 24.6, "fp_ecr": 1, "fp_pos_rank": "QB1"},
        {"player_key": "p2", "name": "Travis Etienne Jr.", "position": "RB", "eligible_positions": ["RB"], "current_slot": "RB", "status": "Q", "fp_proj": 6.4, "fp_ecr": 36, "fp_pos_rank": "RB36"},
        {"player_key": "p3", "name": "CeeDee Lamb", "position": "WR", "eligible_positions": ["WR"], "current_slot": "WR", "status": "BYE", "fp_proj": 0.0, "fp_ecr": 45, "fp_pos_rank": "WR45"},
        {"player_key": "p4", "name": "George Kittle", "position": "TE", "eligible_positions": ["TE"], "current_slot": "TE", "status": "Healthy", "fp_proj": 12.6, "fp_ecr": 1, "fp_pos_rank": "TE1"},
        {"player_key": "p5", "name": "Christian Kirk", "position": "WR", "eligible_positions": ["WR"], "current_slot": "W/R/T", "status": "Healthy", "fp_proj": 9.2, "fp_ecr": 36, "fp_pos_rank": "WR36"},
        # Bench upgrades
        {"player_key": "p6", "name": "JK Dobbins", "position": "RB", "eligible_positions": ["RB"], "current_slot": "BN", "status": "Healthy", "fp_proj": 13.7, "fp_ecr": 17, "fp_pos_rank": "RB17"},
        {"player_key": "p7", "name": "Brian Thomas Jr.", "position": "WR", "eligible_positions": ["WR"], "current_slot": "BN", "status": "Healthy", "fp_proj": 13.1, "fp_ecr": 18, "fp_pos_rank": "WR18"},
    ]

    res = solve_optimal_lineup(players, roster_slots)
    assert res["optimal_projected_total"] > res["current_projected_total"]
    assert res["net_gain"] == round((24.6 + 13.7 + 13.1 + 12.6 + 9.2) - (24.6 + 6.4 + 0.0 + 12.6 + 9.2), 1)
    assert len(res["swaps"]) == 2

    by_key = {p["player_key"]: p for p in res["players"]}
    # CeeDee Lamb (BYE) and Travis Etienne (6.4) should be on the bench
    assert by_key["p3"]["is_starter_optimal"] is False
    assert by_key["p2"]["is_starter_optimal"] is False
    # JK Dobbins and Brian Thomas Jr. should be promoted to starters
    assert by_key["p6"]["is_starter_optimal"] is True
    assert by_key["p7"]["is_starter_optimal"] is True


def test_free_agent_analyzer_finds_starter_and_bench_upgrades():
    roster_slots = ["QB", "RB", "WR", "TE", "DEF", "BN"]
    optimized_roster = [
        {"player_key": "p1", "name": "Josh Allen", "position": "QB", "eligible_positions": ["QB"], "current_slot": "QB", "optimal_slot": "QB", "is_starter_optimal": True, "status": "Healthy", "fp_proj": 24.6, "fp_ecr": 1},
        {"player_key": "p2", "name": "Saquon Barkley", "position": "RB", "eligible_positions": ["RB"], "current_slot": "RB", "optimal_slot": "RB", "is_starter_optimal": True, "status": "Healthy", "fp_proj": 19.8, "fp_ecr": 1},
        {"player_key": "p3", "name": "Terry McLaurin", "position": "WR", "eligible_positions": ["WR"], "current_slot": "WR", "optimal_slot": "WR", "is_starter_optimal": True, "status": "Healthy", "fp_proj": 15.0, "fp_ecr": 7},
        {"player_key": "p4", "name": "George Kittle", "position": "TE", "eligible_positions": ["TE"], "current_slot": "TE", "optimal_slot": "TE", "is_starter_optimal": True, "status": "Healthy", "fp_proj": 12.6, "fp_ecr": 1},
        {"player_key": "p5", "name": "New York Jets", "position": "DEF", "eligible_positions": ["DEF"], "current_slot": "DEF", "optimal_slot": "DEF", "is_starter_optimal": True, "status": "Healthy", "fp_proj": 6.8, "fp_ecr": 12},
        {"player_key": "p6", "name": "DeAndre Hopkins", "position": "WR", "eligible_positions": ["WR"], "current_slot": "BN", "optimal_slot": "BN", "is_starter_optimal": False, "status": "Healthy", "fp_proj": 9.6, "fp_ecr": 34},
    ]
    free_agents = [
        {"player_key": "fa1", "name": "Denver Broncos", "team": "DEN", "position": "DEF", "eligible_positions": ["DEF"], "status": "Healthy", "fp_proj": 9.4, "fp_ecr": 2, "fp_pos_rank": "DST2"},
        {"player_key": "fa2", "name": "Tank Bigsby", "team": "JAX", "position": "RB", "eligible_positions": ["RB"], "status": "Healthy", "fp_proj": 12.4, "fp_ecr": 22, "fp_pos_rank": "RB22"},
    ]

    recs = analyze_free_agent_upgrades(optimized_roster, free_agents, roster_slots)
    assert len(recs) == 2
    assert recs[0]["name"] == "Denver Broncos"
    assert recs[0]["recommendation_type"] == "starter_upgrade"
    assert recs[0]["net_starter_gain"] == 2.6
    assert recs[1]["name"] == "Tank Bigsby"
    assert recs[1]["recommendation_type"] == "bench_upgrade"


def test_build_yahoo_roster_put_xml():
    xml = build_roster_put_xml(
        week=7,
        player_positions=[
            {"player_key": "449.p.31002", "position": "QB"},
            {"player_key": "449.p.34018", "position": "WR"},
        ],
    )
    assert "<coverage_type>week</coverage_type>" in xml
    assert "<week>7</week>" in xml
    assert "<player_key>449.p.34018</player_key>" in xml
    assert "<position>WR</position>" in xml


@pytest.mark.asyncio
async def test_end_to_end_pipeline_and_apply_lineup():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        res = await run_daily_autopilot_pipeline(
            db=db,
            trigger_source="test",
            send_email=False,
            attempt_live_fp=False,
        )
        assert res["leagues_processed"] == 3
        assert res["total_swaps_recommended"] >= 5
        assert res["total_fa_upgrades"] >= 5

        apply_res = await apply_optimal_lineup_for_league(db, "449.l.884120")
        assert apply_res["swaps_applied"] >= 2
        assert apply_res["yahoo_response"]["simulated"] is True
        assert "<roster>" in apply_res["yahoo_response"]["xml_payload"]
    finally:
        db.close()
