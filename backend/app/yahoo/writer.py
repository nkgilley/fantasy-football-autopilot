import logging
import re
from typing import Any
from bs4 import BeautifulSoup
import httpx
from sqlalchemy.orm import Session

from app.settings_store import get_effective_settings
from app.yahoo.auth import get_valid_access_token
from app.yahoo.client import YAHOO_API_BASE

logger = logging.getLogger(__name__)

YAHOO_WEB_BASE = "https://football.fantasysports.yahoo.com"


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


def _build_yahoo_cookie_jar(raw_cookie: str) -> httpx.Cookies:
    jar = httpx.Cookies()
    for part in raw_cookie.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            k_clean = k.strip()
            v_clean = v.strip()
            if k_clean:
                jar.set(k_clean, v_clean, domain=".yahoo.com")
    return jar


def _parse_league_and_team_id(team_key: str) -> tuple[str, str]:
    """
    Extracts (league_id, team_id) from a Yahoo team_key such as '470.l.845478.t.2'.
    """
    m = re.match(r"^\d+\.l\.(\d+)\.t\.(\d+)$", team_key.strip())
    if not m:
        raise ValueError(f"Invalid Yahoo team_key format: {team_key}")
    return m.group(1), m.group(2)


async def _apply_lineup_via_cookie(
    yahoo_cookie: str,
    team_key: str,
    week: int,
    player_positions: list[dict[str, str]],
    xml_payload: str,
) -> dict[str, Any]:
    """
    Updates a team's starting lineup directly via Yahoo Fantasy's web #roster-edit-form
    using the user's browser session cookie and anti-CSRF crumb.
    This bypasses Yahoo's discontinuation of OAuth Write (fspt-w) permissions on new developer apps.
    """
    league_id, team_id = _parse_league_and_team_id(team_key)
    team_url = f"{YAHOO_WEB_BASE}/f1/{league_id}/{team_id}?week={week}"
    jar = _build_yahoo_cookie_jar(yahoo_cookie)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
        ),
        "Origin": YAHOO_WEB_BASE,
        "Referer": team_url,
    }

    desired_by_pid: dict[str, str] = {}
    for item in player_positions:
        pk = str(item.get("player_key", ""))
        pid = pk.split(".p.")[-1] if ".p." in pk else pk
        desired_by_pid[pid] = str(item.get("position", "BN"))

    async with httpx.AsyncClient(cookies=jar, headers=headers, follow_redirects=True, timeout=20.0) as client:
        page_resp = await client.get(team_url)
        page_resp.raise_for_status()

        if "login.yahoo.com" in str(page_resp.url):
            raise PermissionError(
                "Yahoo Browser Session Cookie is expired or missing login session cookies. "
                "Please refresh your Cookie in Settings & OAuth -> Option A."
            )

        soup = BeautifulSoup(page_resp.text, "html.parser")
        form = soup.find("form", id="roster-edit-form")
        if not form:
            raise RuntimeError(
                f"Could not locate #roster-edit-form on {team_url}. Ensure the cookie belongs to the manager of team {team_key}."
            )

        form_data: dict[str, str] = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                form_data[name] = inp.get("value", "")

        updated_count = 0
        for sel in form.find_all("select"):
            pid = sel.get("name")
            if not pid:
                continue
            valid_options = [opt.get("value") for opt in sel.find_all("option") if opt.get("value") is not None]
            selected_opt = sel.find("option", selected=True)
            current_val = selected_opt.get("value") if selected_opt else (valid_options[0] if valid_options else "BN")

            target_val = desired_by_pid.get(pid, current_val)
            if target_val in valid_options:
                form_data[pid] = target_val
                if target_val != current_val:
                    updated_count += 1
            else:
                form_data[pid] = current_val

        action_path = form.get("action") or f"/f1/{league_id}/{team_id}/editroster"
        post_url = action_path if action_path.startswith("http") else f"{YAHOO_WEB_BASE}{action_path}"

        post_resp = await client.post(post_url, data=form_data)
        post_resp.raise_for_status()

    logger.info(
        "Applied Yahoo lineup via web session cookie for %s (week=%s, changed=%s)",
        team_key,
        week,
        updated_count,
    )
    return {
        "executed_live": True,
        "simulated": False,
        "reason": "live_yahoo_cookie",
        "endpoint": f"POST {post_url}",
        "week": week,
        "players_updated": len(player_positions),
        "slots_changed": updated_count,
        "xml_payload": xml_payload,
    }


async def apply_yahoo_lineup_changes(
    db: Session,
    team_key: str,
    week: int,
    player_positions: list[dict[str, str]],
    dry_run: bool = True,
    is_demo: bool = False,
) -> dict[str, Any]:
    """
    Submits lineup slot assignments to Yahoo Fantasy, or simulates the request if dry_run/is_demo is active.
    Prefers the browser session cookie (#roster-edit-form POST) because Yahoo discontinued OAuth Write (fspt-w)
    on newly created self-serve Developer Apps.
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

    eff = get_effective_settings(db)
    yahoo_cookie = (eff.get("yahoo_cookie") or "").strip()

    # 1. Use Yahoo Browser Session Cookie if available (supports full Read/Write even when OAuth app is Read-Only)
    if yahoo_cookie:
        return await _apply_lineup_via_cookie(
            yahoo_cookie=yahoo_cookie,
            team_key=team_key,
            week=week,
            player_positions=player_positions,
            xml_payload=xml_payload,
        )

    # 2. Otherwise try OAuth2 Bearer Token against fantasysports.yahooapis.com
    access_token = await get_valid_access_token(db)
    url = f"{YAHOO_API_BASE}/team/{team_key}/roster"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/xml",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.put(url, content=xml_payload.encode("utf-8"), headers=headers)
        if resp.status_code in (401, 403):
            raise PermissionError(
                f"Yahoo OAuth API returned {resp.status_code} because Yahoo restricted new Developer Apps to Read-Only (fspt-r). "
                "To enable automatic lineup changes, paste your Yahoo Browser Session Cookie in Settings & OAuth (Option A)."
            )
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
