import re
from typing import Any


TEAM_ALIASES: dict[str, str] = {
    "JAC": "JAX",
    "WSH": "WAS",
    "LA": "LAR",
    "GNB": "GB",
    "KAN": "KC",
    "NWE": "NE",
    "NOR": "NO",
    "SFO": "SF",
    "TAM": "TB",
    "LVR": "LV",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
}

DST_TEAM_MAP: dict[str, str] = {
    "arizona": "ARI",
    "arizona cardinals": "ARI",
    "cardinals": "ARI",
    "atlanta": "ATL",
    "atlanta falcons": "ATL",
    "falcons": "ATL",
    "baltimore": "BAL",
    "baltimore ravens": "BAL",
    "ravens": "BAL",
    "buffalo": "BUF",
    "buffalo bills": "BUF",
    "bills": "BUF",
    "carolina": "CAR",
    "carolina panthers": "CAR",
    "panthers": "CAR",
    "chicago": "CHI",
    "chicago bears": "CHI",
    "bears": "CHI",
    "cincinnati": "CIN",
    "cincinnati bengals": "CIN",
    "bengals": "CIN",
    "cleveland": "CLE",
    "cleveland browns": "CLE",
    "browns": "CLE",
    "dallas": "DAL",
    "dallas cowboys": "DAL",
    "cowboys": "DAL",
    "denver": "DEN",
    "denver broncos": "DEN",
    "broncos": "DEN",
    "detroit": "DET",
    "detroit lions": "DET",
    "lions": "DET",
    "green bay": "GB",
    "green bay packers": "GB",
    "packers": "GB",
    "houston": "HOU",
    "houston texans": "HOU",
    "texans": "HOU",
    "indianapolis": "IND",
    "indianapolis colts": "IND",
    "colts": "IND",
    "jacksonville": "JAX",
    "jacksonville jaguars": "JAX",
    "jaguars": "JAX",
    "kansas city": "KC",
    "kansas city chiefs": "KC",
    "chiefs": "KC",
    "las vegas": "LV",
    "las vegas raiders": "LV",
    "raiders": "LV",
    "los angeles chargers": "LAC",
    "la chargers": "LAC",
    "chargers": "LAC",
    "los angeles rams": "LAR",
    "la rams": "LAR",
    "rams": "LAR",
    "miami": "MIA",
    "miami dolphins": "MIA",
    "dolphins": "MIA",
    "minnesota": "MIN",
    "minnesota vikings": "MIN",
    "vikings": "MIN",
    "new england": "NE",
    "new england patriots": "NE",
    "patriots": "NE",
    "new orleans": "NO",
    "new orleans saints": "NO",
    "saints": "NO",
    "new york giants": "NYG",
    "ny giants": "NYG",
    "giants": "NYG",
    "new york jets": "NYJ",
    "ny jets": "NYJ",
    "jets": "NYJ",
    "philadelphia": "PHI",
    "philadelphia eagles": "PHI",
    "eagles": "PHI",
    "pittsburgh": "PIT",
    "pittsburgh steelers": "PIT",
    "steelers": "PIT",
    "san francisco": "SF",
    "san francisco 49ers": "SF",
    "49ers": "SF",
    "seattle": "SEA",
    "seattle seahawks": "SEA",
    "seahawks": "SEA",
    "tampa bay": "TB",
    "tampa bay buccaneers": "TB",
    "buccaneers": "TB",
    "tennessee": "TEN",
    "tennessee titans": "TEN",
    "titans": "TEN",
    "washington": "WAS",
    "washington commanders": "WAS",
    "commanders": "WAS",
}

SUFFIX_PATTERN = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.IGNORECASE)
NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9\s]")
MULTISPACE_PATTERN = re.compile(r"\s+")


def normalize_team(team: str) -> str:
    if not team:
        return ""
    cleaned = team.strip().upper()
    return TEAM_ALIASES.get(cleaned, cleaned)


def normalize_position(pos: str) -> str:
    if not pos:
        return ""
    cleaned = pos.strip().upper()
    if cleaned in ("DST", "D/ST", "DEF"):
        return "DEF"
    if cleaned == "PK":
        return "K"
    return cleaned


def normalize_player_name(name: str, position: str = "", team: str = "") -> str:
    if not name:
        return ""
    norm_pos = normalize_position(position)
    # Remove parenthetical team tags like "Baltimore Ravens (BAL)"
    stripped = re.sub(r"\([^)]*\)", "", name).strip().lower()
    if norm_pos == "DEF":
        for phrase, abbr in DST_TEAM_MAP.items():
            if phrase in stripped:
                return f"def_{abbr.lower()}"
        if team:
            return f"def_{normalize_team(team).lower()}"

    no_suffix = SUFFIX_PATTERN.sub("", stripped)
    # Normalize common nickname/spelling differences
    no_suffix = no_suffix.replace("de'von", "devon").replace("ja'marr", "jamarr")
    alnum = NON_ALNUM_PATTERN.sub("", no_suffix)
    collapsed = MULTISPACE_PATTERN.sub(" ", alnum).strip()
    return collapsed


def match_player_to_fp(
    player_name: str,
    position: str,
    team: str,
    fp_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Matches a Yahoo player against the FantasyPros weekly index.
    Tries exact (normalized_name, position, team), then (normalized_name, position),
    then (normalized_name).
    """
    norm_name = normalize_player_name(player_name, position, team)
    norm_pos = normalize_position(position)
    norm_team = normalize_team(team)

    key_full = f"{norm_name}|{norm_pos}|{norm_team}"
    if key_full in fp_index:
        return fp_index[key_full]

    key_pos = f"{norm_name}|{norm_pos}"
    if key_pos in fp_index:
        return fp_index[key_pos]

    if norm_name in fp_index:
        return fp_index[norm_name]

    # Defense fallback by team code
    if norm_pos == "DEF" and norm_team:
        def_key = f"def_{norm_team.lower()}|DEF"
        if def_key in fp_index:
            return fp_index[def_key]

    return None
