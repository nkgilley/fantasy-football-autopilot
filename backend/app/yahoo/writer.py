import logging
from typing import Any
import httpx
from sqlalchemy.orm import Session

from app.yahoo.auth import get_valid_access_token
from app.yahoo.client import YAHOO_API_BASE

logger = logging.getLogger(__name__)


def build_roster_put_xml(week: int, player_positions: list[dict[str, str]]) -> str:
    """
    Constructs the official Yahoo Fantasy Sports v2 XML payload for updating a team's starting lineup.
    Reference: PUT https://fantasysports.yahooapis.com/fantasy/v2/team/{team_key}/roster
    """
    player_nodes = []
    for item in player_positions:
        pk = item["player_key"]
        pos = item["position"]
        player_nodes.append(
            f"    <player>\n"
            f"      <player_key>{pk}</player_key>\n"
            f"      <position>{pos}</position>\n"
            f"    </player>"
        )
    players_xml = "\n".join(player_nodes)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<fantasy_content>\n"
        "  <roster>\n"
        "    <coverage_type>week</coverage_type>\n"
        f"    <week>{week}</week>\n"
        "    <players>\n"
        f"{players_xml}\n"
        "    </players>\n"
        "  </roster>\n"
        "</fantasy_content>"
    )


async def apply_yahoo_lineup_changes(
    db: Session,
    team_key: str,
    week: int,
    player_positions: list[dict[str, str]],
    dry_run: bool = True,
    is_demo: bool = False,
) -> dict[str, Any]:
    """
    Submits lineup slot assignments to Yahoo Fantasy API, or simulates the request if dry_run/is_demo is active.
    """
    xml_payload = build_roster_put_xml(week, player_positions)

    if dry_run or is_demo:
        mode_reason = "demo_league" if is_demo else "dry_run_enabled"
        logger.info("Simulated Yahoo PUT /team/%s/roster (week=%s, reason=%s)", team_key, week, mode_reason)
        return {
            "executed_live": False,
            "simulated": True,
            "reason": mode_reason,
            "endpoint": f"PUT {YAHOO_API_BASE}/team/{team_key}/roster",
            "week": week,
            "players_updated": len(player_positions),
            "xml_payload": xml_payload,
        }

    access_token = await get_valid_access_token(db)
    url = f"{YAHOO_API_BASE}/team/{team_key}/roster"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/xml",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.put(url, content=xml_payload.encode("utf-8"), headers=headers)
        resp.raise_for_status()

    return {
        "executed_live": True,
        "simulated": False,
        "reason": "live_yahoo_api",
        "endpoint": f"PUT {url}",
        "week": week,
        "players_updated": len(player_positions),
        "xml_payload": xml_payload,
    }
