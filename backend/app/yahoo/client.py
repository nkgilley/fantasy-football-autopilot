import logging
from typing import Any
import httpx
from sqlalchemy.orm import Session

from app.settings_store import get_effective_settings
from app.yahoo.auth import get_valid_access_token

logger = logging.getLogger(__name__)

YAHOO_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
YAHOO_PUB_RO_BASE = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2"


def _flatten_yahoo_list(items: Any) -> dict[str, Any]:
    """
    Yahoo's JSON API represents objects as lists of single-key dicts mixed with metadata.
    This helper merges all dict elements in a list into a single dict.
    """
    merged: dict[str, Any] = {}
    if isinstance(items, dict):
        return items
    if isinstance(items, list):
        for el in items:
            if isinstance(el, dict):
                merged.update(el)
            elif isinstance(el, list):
                merged.update(_flatten_yahoo_list(el))
    return merged


class YahooFantasyClient:
    def __init__(self, access_token: str = "", yahoo_cookie: str = ""):
        self.access_token = access_token.strip()
        self.yahoo_cookie = yahoo_cookie.strip()

    async def _get(self, resource_path: str) -> dict[str, Any]:
        sep = "&" if "?" in resource_path else "?"
        clean_path = f"{resource_path.lstrip('/')}{sep}format=json"

        # 1. If a browser session cookie is configured, prefer pub-api-ro (bypasses Yahoo's OAuth app 403 gate)
        if self.yahoo_cookie:
            url = f"{YAHOO_PUB_RO_BASE}/{clean_path}"
            headers = {
                "Cookie": self.yahoo_cookie,
                "Origin": "https://football.fantasysports.yahoo.com",
                "Referer": "https://football.fantasysports.yahoo.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
            async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
                resp = await client.get(url)
                if resp.status_code in (401, 403):
                    raise PermissionError(
                        f"Yahoo Browser Cookie returned HTTP {resp.status_code}. "
                        "Make sure you copied the Cookie or 'Copy as cURL' while logged into football.fantasysports.yahoo.com."
                    )
                resp.raise_for_status()
                return resp.json()

        # 2. Otherwise use Official OAuth2 Bearer Token against fantasysports.yahooapis.com
        url = f"{YAHOO_API_BASE}/{clean_path}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 403:
                raise PermissionError(
                    "Yahoo blocked your new OAuth App ID with 403 ('This application is not authorized to perform this action') — "
                    "Yahoo requires manual backend whitelisting for new Developer App IDs on fantasysports.yahooapis.com. "
                    "Use 'Option B: Instant Browser Session Connect (Copy as cURL / Cookie)' in Settings & OAuth to bypass Yahoo's app gate immediately!"
                )
            resp.raise_for_status()
            return resp.json()

    async def fetch_user_nfl_leagues(self) -> list[dict[str, Any]]:
        """
        Discovers all active NFL leagues for the logged-in Yahoo user,
        along with settings, roster positions, scoring type, and user's team.
        """
        data = await self._get("users;use_login=1/games;game_codes=nfl/leagues")
        league_keys: list[str] = []

        try:
            users = data["fantasy_content"]["users"]
            user_obj = users["0"]["user"]
            games = _flatten_yahoo_list(user_obj[1:]).get("games", {})
            game_count = int(games.get("count", 0))

            season_leagues: list[tuple[int, list[str]]] = []
            for g_idx in range(game_count):
                game_arr = games.get(str(g_idx), {}).get("game", [])
                if not game_arr:
                    continue
                g_meta = _flatten_yahoo_list(game_arr[0])
                g_sub = _flatten_yahoo_list(game_arr[1:])
                season = int(g_meta.get("season", 0) or 0)
                leagues_box = g_sub.get("leagues", {})
                if not isinstance(leagues_box, dict):
                    continue
                l_count = int(leagues_box.get("count", 0) or 0)
                keys_for_season: list[str] = []
                for l_idx in range(l_count):
                    l_entry = leagues_box.get(str(l_idx), {}).get("league", [])
                    if not l_entry:
                        continue
                    l_meta = _flatten_yahoo_list(l_entry[0])
                    lk = str(l_meta.get("league_key", ""))
                    if lk:
                        keys_for_season.append(lk)
                if keys_for_season:
                    season_leagues.append((season, keys_for_season))

            if season_leagues:
                season_leagues.sort(key=lambda x: x[0], reverse=True)
                league_keys = season_leagues[0][1]
        except Exception as exc:
            logger.error("Error discovering Yahoo NFL league keys: %s", exc)
            raise

        leagues_out: list[dict[str, Any]] = []
        for lk in league_keys:
            try:
                lg_data = await self._get(f"league/{lk};out=settings,standings,teams")
                league_entry = lg_data["fantasy_content"]["league"]
                meta = _flatten_yahoo_list(league_entry[0])
                sub = _flatten_yahoo_list(league_entry[1:])

                roster_slots, scoring_type = self._parse_league_settings(sub.get("settings", []))
                my_team = self._find_my_team_in_standings(sub.get("standings", []), sub.get("teams", {}))

                if not my_team.get("team_key"):
                    t_data = await self._get(f"users;use_login=1/games/leagues;league_keys={lk}/teams")
                    my_team = self._parse_direct_user_team(t_data)

                leagues_out.append(
                    {
                        "league_key": lk,
                        "league_id": str(meta.get("league_id", "")),
                        "name": str(meta.get("name", "Yahoo NFL League")),
                        "season": int(meta.get("season", 2026)),
                        "current_week": int(meta.get("current_week", 1) or 1),
                        "num_teams": int(meta.get("num_teams", 12) or 12),
                        "scoring_type": scoring_type,
                        "roster_slots": roster_slots,
                        "team_key": my_team.get("team_key", ""),
                        "team_name": my_team.get("team_name", "My Team"),
                        "team_record": my_team.get("record", "0-0-0"),
                        "team_standing": my_team.get("rank", 1),
                        "points_for": my_team.get("points_for", 0.0),
                        "points_against": my_team.get("points_against", 0.0),
                        "faab_balance": my_team.get("faab_balance", 100),
                    }
                )
            except Exception as exc:
                logger.error("Error fetching details for Yahoo league %s: %s", lk, exc)
                raise

        return leagues_out

    def _parse_direct_user_team(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            users = data["fantasy_content"]["users"]
            user_obj = users["0"]["user"]
            games = _flatten_yahoo_list(user_obj[1:]).get("games", {})
            game_arr = games.get("0", {}).get("game", [])
            leagues = _flatten_yahoo_list(game_arr[1:]).get("leagues", {})
            league_arr = leagues.get("0", {}).get("league", [])
            teams = _flatten_yahoo_list(league_arr[1:]).get("teams", {})
            t_arr = teams.get("0", {}).get("team", [])
            t_meta = _flatten_yahoo_list(t_arr[0])
            return {
                "team_key": str(t_meta.get("team_key", "")),
                "team_name": str(t_meta.get("name", "My Team")),
                "record": "0-0-0",
                "rank": 1,
                "points_for": 0.0,
                "points_against": 0.0,
                "faab_balance": int(t_meta.get("faab_balance") or 100),
            }
        except Exception:
            return {}

    def _parse_league_settings(self, settings_node: Any) -> tuple[list[str], str]:
        flat = _flatten_yahoo_list(settings_node)
        roster_slots: list[str] = []
        positions_raw = flat.get("roster_positions", [])
        for item in positions_raw:
            rp = item.get("roster_position", {}) if isinstance(item, dict) else {}
            pos = rp.get("position", "")
            cnt = int(rp.get("count", 1))
            if pos:
                roster_slots.extend([pos] * cnt)

        if not roster_slots:
            roster_slots = ["QB", "RB", "RB", "WR", "WR", "TE", "W/R/T", "K", "DEF", "BN", "BN", "BN", "BN", "BN", "BN", "IR"]

        scoring_type = "half_ppr"
        stat_mods = flat.get("stat_modifiers", {}).get("stats", [])
        for s in stat_mods:
            stat = s.get("stat", {}) if isinstance(s, dict) else {}
            if str(stat.get("stat_id")) == "11":
                val = float(stat.get("value", 0.5))
                if val >= 0.9:
                    scoring_type = "ppr"
                elif val <= 0.1:
                    scoring_type = "std"
                else:
                    scoring_type = "half_ppr"
        return roster_slots, scoring_type

    def _find_my_team_in_standings(self, standings_node: Any, teams_node: Any) -> dict[str, Any]:
        flat_standings = _flatten_yahoo_list(standings_node)
        teams = flat_standings.get("teams") or teams_node or {}
        count = int(teams.get("count", 0)) if isinstance(teams, dict) else 0
        for i in range(count):
            t_arr = teams.get(str(i), {}).get("team", [])
            t_meta = _flatten_yahoo_list(t_arr[0]) if t_arr else {}
            t_sub = _flatten_yahoo_list(t_arr[1:]) if len(t_arr) > 1 else {}
            if str(t_meta.get("is_owned_by_current_login")) == "1":
                ts = _flatten_yahoo_list(t_sub.get("team_standings", {}))
                outcomes = ts.get("outcome_totals", {})
                record = f"{outcomes.get('wins', 0)}-{outcomes.get('losses', 0)}-{outcomes.get('ties', 0)}"
                return {
                    "team_key": str(t_meta.get("team_key", "")),
                    "team_name": str(t_meta.get("name", "My Team")),
                    "record": record,
                    "rank": int(ts.get("rank") or 1),
                    "points_for": float(ts.get("points_for") or 0.0),
                    "points_against": float(ts.get("points_against") or 0.0),
                    "faab_balance": int(t_meta.get("faab_balance") or 100),
                }
        return {}

    async def fetch_team_roster(self, team_key: str, week: int) -> list[dict[str, Any]]:
        if not team_key:
            return []
        data = await self._get(f"team/{team_key}/roster;week={week}/players")
        players_out: list[dict[str, Any]] = []
        try:
            team_arr = data["fantasy_content"]["team"]
            roster = _flatten_yahoo_list(team_arr[1:]).get("roster", {})
            flat_roster = _flatten_yahoo_list(roster)
            players_container = (
                flat_roster.get("players")
                or _flatten_yahoo_list(flat_roster.get("0", {})).get("players")
                or {}
            )
            if not isinstance(players_container, dict):
                return []
            count = int(players_container.get("count", 0))
            for i in range(count):
                p_arr = players_container.get(str(i), {}).get("player", [])
                if not p_arr:
                    continue
                p_meta = _flatten_yahoo_list(p_arr[0])
                p_sub = _flatten_yahoo_list(p_arr[1:])
                sel_node = p_sub.get("selected_position", [])
                if isinstance(sel_node, dict) and "0" in sel_node:
                    sel_node = sel_node["0"]
                selected_pos = _flatten_yahoo_list(sel_node).get("position", "BN")
                elig = [
                    e.get("position")
                    for e in p_meta.get("eligible_positions", [])
                    if isinstance(e, dict) and e.get("position")
                ]
                name_obj = p_meta.get("name", {})
                full_name = name_obj.get("full") if isinstance(name_obj, dict) else str(name_obj)
                bye_weeks = p_meta.get("bye_weeks", {})
                bye_week = int(bye_weeks.get("week", 0)) if isinstance(bye_weeks, dict) else 0
                status = str(p_meta.get("status", "") or "Healthy")
                if bye_week == week:
                    status = "BYE"
                is_editable = str(p_sub.get("is_editable", "1")) != "0"
                players_out.append(
                    {
                        "player_key": str(p_meta.get("player_key", "")),
                        "name": full_name,
                        "team": str(p_meta.get("editorial_team_abbr", "")).upper(),
                        "position": str(p_meta.get("display_position", "RB")).split(",")[0].strip(),
                        "eligible_positions": elig or ["RB"],
                        "current_slot": selected_pos,
                        "status": status,
                        "injury_note": str(p_meta.get("status_full", "")),
                        "bye_week": bye_week,
                        "is_editable": is_editable,
                    }
                )
        except Exception as exc:
            logger.error("Failed parsing Yahoo roster for %s: %s", team_key, exc)
            raise
        return players_out

    async def fetch_team_matchups(self, team_key: str, current_week: int) -> dict[str, Any]:
        default_matchup: dict[str, Any] = {
            "week": current_week,
            "my_projected_points": 0.0,
            "opponent_team_name": "Opponent",
            "opponent_manager": "",
            "opponent_record": "0-0-0",
            "opponent_projected_points": 0.0,
            "win_probability": 50.0,
            "schedule": [],
        }
        if not team_key:
            return default_matchup

        try:
            data = await self._get(f"team/{team_key}/matchups")
            schedule: list[dict[str, Any]] = []
            current_matchup = dict(default_matchup)
            team_arr = data["fantasy_content"]["team"]
            matchups = _flatten_yahoo_list(team_arr[1:]).get("matchups", {})
            if not isinstance(matchups, dict):
                return default_matchup
            count = int(matchups.get("count", 0))
            for i in range(count):
                m_obj = matchups.get(str(i), {}).get("matchup", {})
                flat_m = _flatten_yahoo_list(m_obj)
                wk = int(flat_m.get("week", i + 1))
                teams_box = _flatten_yahoo_list(flat_m.get("0", flat_m)).get("teams", {})
                if isinstance(teams_box, dict) and int(teams_box.get("count", 0)) >= 2:
                    t0 = teams_box["0"]["team"]
                    t1 = teams_box["1"]["team"]
                    t0_meta, t0_sub = _flatten_yahoo_list(t0[0]), _flatten_yahoo_list(t0[1:])
                    t1_meta, t1_sub = _flatten_yahoo_list(t1[0]), _flatten_yahoo_list(t1[1:])
                    if str(t0_meta.get("team_key")) == team_key:
                        me_meta, me_sub, opp_meta, opp_sub = t0_meta, t0_sub, t1_meta, t1_sub
                    else:
                        me_meta, me_sub, opp_meta, opp_sub = t1_meta, t1_sub, t0_meta, t0_sub

                    my_proj = float(me_sub.get("team_projected_points", {}).get("total", 0.0) or 0.0)
                    my_pts = float(me_sub.get("team_points", {}).get("total", 0.0) or 0.0)
                    opp_proj = float(opp_sub.get("team_projected_points", {}).get("total", 0.0) or 0.0)
                    opp_pts = float(opp_sub.get("team_points", {}).get("total", 0.0) or 0.0)
                    win_prob = round(float(me_sub.get("win_probability", 0.5) or 0.5) * 100, 1)
                    opp_name = str(opp_meta.get("name", "Opponent"))

                    schedule.append(
                        {
                            "week": wk,
                            "opponent_name": opp_name,
                            "my_points": my_pts,
                            "my_projected": my_proj,
                            "opponent_points": opp_pts,
                            "opponent_projected": opp_proj,
                            "status": str(flat_m.get("status", "preevent")),
                        }
                    )
                    if wk == current_week:
                        current_matchup = {
                            "week": wk,
                            "my_projected_points": my_proj,
                            "opponent_team_name": opp_name,
                            "opponent_manager": "",
                            "opponent_record": "0-0-0",
                            "opponent_projected_points": opp_proj,
                            "win_probability": win_prob,
                        }
            current_matchup["schedule"] = schedule
            return current_matchup
        except Exception as exc:
            logger.warning("Failed parsing matchups for %s: %s", team_key, exc)
            return default_matchup

    async def fetch_available_free_agents(self, league_key: str, current_week: int) -> list[dict[str, Any]]:
        positions = ["QB", "RB", "WR", "TE", "K", "DEF"]
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        for pos in positions:
            try:
                data = await self._get(
                    f"league/{league_key}/players;status=A;position={pos};sort=AR;count=15;out=ownership,percent_owned"
                )
                league_arr = data["fantasy_content"]["league"]
                players_box = _flatten_yahoo_list(league_arr[1:]).get("players", {})
                if not isinstance(players_box, dict):
                    continue
                count = int(players_box.get("count", 0))
                for i in range(count):
                    p_arr = players_box.get(str(i), {}).get("player", [])
                    if not p_arr:
                        continue
                    p_meta = _flatten_yahoo_list(p_arr[0])
                    p_sub = _flatten_yahoo_list(p_arr[1:])
                    pk = str(p_meta.get("player_key", ""))
                    if not pk or pk in seen:
                        continue
                    seen.add(pk)
                    name_obj = p_meta.get("name", {})
                    full_name = name_obj.get("full") if isinstance(name_obj, dict) else str(name_obj)
                    elig = [
                        e.get("position")
                        for e in p_meta.get("eligible_positions", [])
                        if isinstance(e, dict) and e.get("position")
                    ]
                    bye_weeks = p_meta.get("bye_weeks", {})
                    bye_week = int(bye_weeks.get("week", 0)) if isinstance(bye_weeks, dict) else 0
                    status = str(p_meta.get("status", "") or "Healthy")
                    if bye_week == current_week:
                        status = "BYE"
                    ownership_info = _flatten_yahoo_list(p_sub.get("ownership", {}))
                    own_type = "W" if ownership_info.get("ownership_type") == "waivers" else "FA"
                    pct_owned_node = _flatten_yahoo_list(p_sub.get("percent_owned", {}))
                    pct_owned = float(pct_owned_node.get("value", 0.0) or 0.0)
                    candidates.append(
                        {
                            "player_key": pk,
                            "name": full_name,
                            "team": str(p_meta.get("editorial_team_abbr", "")).upper(),
                            "position": pos,
                            "eligible_positions": elig or [pos],
                            "availability_type": own_type,
                            "percent_owned": pct_owned,
                            "status": status,
                            "bye_week": bye_week,
                        }
                    )
            except Exception as exc:
                logger.warning("Failed fetching Yahoo free agents for %s (%s): %s", league_key, pos, exc)

        return candidates

    async def fetch_league_teams_overview(self, league_key: str, current_week: int) -> list[dict[str, Any]]:
        """
        Fetches all teams in a Yahoo league along with their standings, records, manager names,
        and full weekly rosters in a single request (`league/{league_key}/teams;out=standings,roster;week={week}`).
        """
        data = await self._get(f"league/{league_key}/teams;out=standings,roster;week={current_week}")
        teams_out: list[dict[str, Any]] = []
        try:
            league_arr = data["fantasy_content"]["league"]
            sub = _flatten_yahoo_list(league_arr[1:])
            teams_box = sub.get("teams", {})
            if not isinstance(teams_box, dict):
                return []
            count = int(teams_box.get("count", 0))
            for i in range(count):
                t_arr = teams_box.get(str(i), {}).get("team", [])
                if not t_arr:
                    continue
                t_meta = _flatten_yahoo_list(t_arr[0])
                t_sub = _flatten_yahoo_list(t_arr[1:])

                # Manager info
                mgr_name = "Manager"
                managers = t_meta.get("managers", [])
                if isinstance(managers, list) and managers:
                    first_m = managers[0]
                    if isinstance(first_m, dict):
                        mgr_name = str(first_m.get("manager", {}).get("nickname", "Manager"))

                # Standings info
                ts = _flatten_yahoo_list(t_sub.get("team_standings", {}))
                outcomes = ts.get("outcome_totals", {})
                record = f"{outcomes.get('wins', 0)}-{outcomes.get('losses', 0)}-{outcomes.get('ties', 0)}"
                streak_node = ts.get("streak", {})
                streak_str = ""
                if isinstance(streak_node, dict) and streak_node.get("type") and streak_node.get("value"):
                    prefix = "W" if str(streak_node.get("type")).lower().startswith("w") else "L"
                    streak_str = f"{prefix}{streak_node.get('value')}"

                # Roster players
                flat_roster = _flatten_yahoo_list(t_sub.get("roster", {}))
                players_container = (
                    flat_roster.get("players")
                    or _flatten_yahoo_list(flat_roster.get("0", {})).get("players")
                    or {}
                )
                roster_players: list[dict[str, Any]] = []
                if isinstance(players_container, dict):
                    p_count = int(players_container.get("count", 0))
                    for j in range(p_count):
                        p_arr = players_container.get(str(j), {}).get("player", [])
                        if not p_arr:
                            continue
                        p_meta = _flatten_yahoo_list(p_arr[0])
                        p_sub = _flatten_yahoo_list(p_arr[1:])
                        sel_node = p_sub.get("selected_position", [])
                        if isinstance(sel_node, dict) and "0" in sel_node:
                            sel_node = sel_node["0"]
                        selected_pos = _flatten_yahoo_list(sel_node).get("position", "BN")
                        elig = [
                            e.get("position")
                            for e in p_meta.get("eligible_positions", [])
                            if isinstance(e, dict) and e.get("position")
                        ]
                        name_obj = p_meta.get("name", {})
                        full_name = name_obj.get("full") if isinstance(name_obj, dict) else str(name_obj)
                        bye_weeks = p_meta.get("bye_weeks", {})
                        bye_week = int(bye_weeks.get("week", 0)) if isinstance(bye_weeks, dict) else 0
                        status = str(p_meta.get("status", "") or "Healthy")
                        if bye_week == current_week:
                            status = "BYE"
                        is_editable = str(p_sub.get("is_editable", "1")) != "0"
                        roster_players.append(
                            {
                                "player_key": str(p_meta.get("player_key", "")),
                                "name": full_name,
                                "team": str(p_meta.get("editorial_team_abbr", "")).upper(),
                                "position": str(p_meta.get("display_position", "RB")).split(",")[0].strip(),
                                "eligible_positions": elig or ["RB"],
                                "current_slot": selected_pos,
                                "status": status,
                                "injury_note": str(p_meta.get("status_full", "")),
                                "bye_week": bye_week,
                                "is_editable": is_editable,
                            }
                        )

                teams_out.append(
                    {
                        "team_key": str(t_meta.get("team_key", "")),
                        "team_name": str(t_meta.get("name", f"Team {i + 1}")),
                        "manager_name": mgr_name,
                        "is_my_team": str(t_meta.get("is_owned_by_current_login")) == "1",
                        "rank": int(ts.get("rank") or (i + 1)),
                        "record": record,
                        "streak": streak_str,
                        "points_for": float(ts.get("points_for") or 0.0),
                        "points_against": float(ts.get("points_against") or 0.0),
                        "waiver_priority": int(t_meta.get("waiver_priority") or 0),
                        "number_of_moves": int(t_meta.get("number_of_moves") or 0),
                        "faab_balance": int(t_meta.get("faab_balance") or 100),
                        "roster": roster_players,
                    }
                )
        except Exception as exc:
            logger.error("Failed parsing league teams overview for %s: %s", league_key, exc)
            raise

        teams_out.sort(key=lambda t: t["rank"])
        return teams_out


async def get_yahoo_client(db: Session) -> YahooFantasyClient:
    eff = get_effective_settings(db)
    cookie = (eff.get("yahoo_cookie") or "").strip()
    if cookie:
        return YahooFantasyClient(access_token="", yahoo_cookie=cookie)
    token = await get_valid_access_token(db)
    return YahooFantasyClient(access_token=token, yahoo_cookie="")
