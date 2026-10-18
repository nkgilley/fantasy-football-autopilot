import json
import logging
import re
from typing import Any
import httpx
from bs4 import BeautifulSoup

from app.fantasypros.matcher import (
    normalize_player_name,
    normalize_position,
    normalize_team,
)

logger = logging.getLogger(__name__)

ECR_SCRIPT_REGEX = re.compile(r"var\s+ecrData\s*=\s*(\{.*?\});", re.DOTALL)

# Position URL slugs on FantasyPros by scoring type
FP_RANKING_SLUGS: dict[str, dict[str, str]] = {
    "std": {
        "QB": "qb",
        "RB": "rb",
        "WR": "wr",
        "TE": "te",
        "K": "k",
        "DEF": "dst",
    },
    "half_ppr": {
        "QB": "qb",
        "RB": "half-point-ppr-rb",
        "WR": "half-point-ppr-wr",
        "TE": "half-point-ppr-te",
        "K": "k",
        "DEF": "dst",
    },
    "ppr": {
        "QB": "qb",
        "RB": "ppr-rb",
        "WR": "ppr-wr",
        "TE": "ppr-te",
        "K": "k",
        "DEF": "dst",
    },
}

# Built-in baseline weekly ECR & projections (Half-PPR base with receptions estimate for STD/PPR adjustment)
BASELINE_WEEKLY_PLAYERS: list[dict[str, Any]] = [
    # QBs
    {"name": "Josh Allen", "team": "BUF", "pos": "QB", "ecr": 1, "pos_rank": "QB1", "tier": 1, "proj": 24.6, "rec": 0.0, "opp": "vs TEN"},
    {"name": "Lamar Jackson", "team": "BAL", "pos": "QB", "ecr": 2, "pos_rank": "QB2", "tier": 1, "proj": 24.1, "rec": 0.0, "opp": "@ TB"},
    {"name": "Jayden Daniels", "team": "WAS", "pos": "QB", "ecr": 3, "pos_rank": "QB3", "tier": 1, "proj": 22.8, "rec": 0.0, "opp": "vs CAR"},
    {"name": "Jalen Hurts", "team": "PHI", "pos": "QB", "ecr": 4, "pos_rank": "QB4", "tier": 1, "proj": 22.3, "rec": 0.0, "opp": "@ NYG"},
    {"name": "Joe Burrow", "team": "CIN", "pos": "QB", "ecr": 5, "pos_rank": "QB5", "tier": 2, "proj": 20.9, "rec": 0.0, "opp": "@ CLE"},
    {"name": "C.J. Stroud", "team": "HOU", "pos": "QB", "ecr": 6, "pos_rank": "QB6", "tier": 2, "proj": 19.8, "rec": 0.0, "opp": "@ GB"},
    {"name": "Jordan Love", "team": "GB", "pos": "QB", "ecr": 7, "pos_rank": "QB7", "tier": 2, "proj": 19.5, "rec": 0.0, "opp": "vs HOU"},
    {"name": "Patrick Mahomes", "team": "KC", "pos": "QB", "ecr": 8, "pos_rank": "QB8", "tier": 2, "proj": 19.1, "rec": 0.0, "opp": "@ SF"},
    {"name": "Baker Mayfield", "team": "TB", "pos": "QB", "ecr": 9, "pos_rank": "QB9", "tier": 2, "proj": 18.8, "rec": 0.0, "opp": "vs BAL"},
    {"name": "Brock Purdy", "team": "SF", "pos": "QB", "ecr": 10, "pos_rank": "QB10", "tier": 2, "proj": 18.5, "rec": 0.0, "opp": "vs KC"},
    {"name": "Kyler Murray", "team": "ARI", "pos": "QB", "ecr": 11, "pos_rank": "QB11", "tier": 3, "proj": 18.2, "rec": 0.0, "opp": "vs LAC"},
    {"name": "Jared Goff", "team": "DET", "pos": "QB", "ecr": 12, "pos_rank": "QB12", "tier": 3, "proj": 17.9, "rec": 0.0, "opp": "@ MIN"},
    {"name": "Sam Darnold", "team": "MIN", "pos": "QB", "ecr": 13, "pos_rank": "QB13", "tier": 3, "proj": 17.6, "rec": 0.0, "opp": "vs DET"},
    {"name": "Drake Maye", "team": "NE", "pos": "QB", "ecr": 14, "pos_rank": "QB14", "tier": 3, "proj": 17.2, "rec": 0.0, "opp": "@ JAX"},
    {"name": "Trevor Lawrence", "team": "JAX", "pos": "QB", "ecr": 15, "pos_rank": "QB15", "tier": 3, "proj": 16.9, "rec": 0.0, "opp": "vs NE"},
    {"name": "Dak Prescott", "team": "DAL", "pos": "QB", "ecr": 24, "pos_rank": "QB24", "tier": 5, "proj": 0.0, "rec": 0.0, "opp": "BYE"},
    {"name": "Caleb Williams", "team": "CHI", "pos": "QB", "ecr": 25, "pos_rank": "QB25", "tier": 5, "proj": 0.0, "rec": 0.0, "opp": "BYE"},

    # RBs
    {"name": "Saquon Barkley", "team": "PHI", "pos": "RB", "ecr": 1, "pos_rank": "RB1", "tier": 1, "proj": 19.8, "rec": 3.6, "opp": "@ NYG"},
    {"name": "Derrick Henry", "team": "BAL", "pos": "RB", "ecr": 2, "pos_rank": "RB2", "tier": 1, "proj": 19.1, "rec": 1.4, "opp": "@ TB"},
    {"name": "Kyren Williams", "team": "LAR", "pos": "RB", "ecr": 3, "pos_rank": "RB3", "tier": 1, "proj": 18.7, "rec": 3.2, "opp": "vs LV"},
    {"name": "Bijan Robinson", "team": "ATL", "pos": "RB", "ecr": 4, "pos_rank": "RB4", "tier": 1, "proj": 18.2, "rec": 4.2, "opp": "vs SEA"},
    {"name": "Jahmyr Gibbs", "team": "DET", "pos": "RB", "ecr": 5, "pos_rank": "RB5", "tier": 1, "proj": 17.6, "rec": 4.0, "opp": "@ MIN"},
    {"name": "Breece Hall", "team": "NYJ", "pos": "RB", "ecr": 6, "pos_rank": "RB6", "tier": 1, "proj": 17.3, "rec": 4.4, "opp": "@ PIT"},
    {"name": "Kenneth Walker III", "team": "SEA", "pos": "RB", "ecr": 7, "pos_rank": "RB7", "tier": 2, "proj": 16.9, "rec": 3.4, "opp": "@ ATL"},
    {"name": "Alvin Kamara", "team": "NO", "pos": "RB", "ecr": 8, "pos_rank": "RB8", "tier": 2, "proj": 16.5, "rec": 5.0, "opp": "vs DEN"},
    {"name": "Joe Mixon", "team": "HOU", "pos": "RB", "ecr": 9, "pos_rank": "RB9", "tier": 2, "proj": 16.2, "rec": 3.0, "opp": "@ GB"},
    {"name": "Josh Jacobs", "team": "GB", "pos": "RB", "ecr": 10, "pos_rank": "RB10", "tier": 2, "proj": 15.8, "rec": 2.8, "opp": "vs HOU"},
    {"name": "De'Von Achane", "team": "MIA", "pos": "RB", "ecr": 11, "pos_rank": "RB11", "tier": 2, "proj": 15.5, "rec": 4.6, "opp": "@ IND"},
    {"name": "Jordan Mason", "team": "SF", "pos": "RB", "ecr": 12, "pos_rank": "RB12", "tier": 2, "proj": 15.1, "rec": 1.6, "opp": "vs KC"},
    {"name": "James Cook", "team": "BUF", "pos": "RB", "ecr": 13, "pos_rank": "RB13", "tier": 3, "proj": 14.8, "rec": 3.0, "opp": "vs TEN"},
    {"name": "David Montgomery", "team": "DET", "pos": "RB", "ecr": 14, "pos_rank": "RB14", "tier": 3, "proj": 14.5, "rec": 2.0, "opp": "@ MIN"},
    {"name": "Aaron Jones", "team": "MIN", "pos": "RB", "ecr": 15, "pos_rank": "RB15", "tier": 3, "proj": 14.2, "rec": 3.4, "opp": "vs DET"},
    {"name": "Chuba Hubbard", "team": "CAR", "pos": "RB", "ecr": 16, "pos_rank": "RB16", "tier": 3, "proj": 13.9, "rec": 3.2, "opp": "@ WAS"},
    {"name": "JK Dobbins", "team": "LAC", "pos": "RB", "ecr": 17, "pos_rank": "RB17", "tier": 3, "proj": 13.7, "rec": 2.4, "opp": "@ ARI"},
    {"name": "Brian Robinson Jr.", "team": "WAS", "pos": "RB", "ecr": 18, "pos_rank": "RB18", "tier": 3, "proj": 13.4, "rec": 1.8, "opp": "vs CAR"},
    {"name": "Tony Pollard", "team": "TEN", "pos": "RB", "ecr": 19, "pos_rank": "RB19", "tier": 3, "proj": 13.1, "rec": 3.2, "opp": "@ BUF"},
    {"name": "Chase Brown", "team": "CIN", "pos": "RB", "ecr": 20, "pos_rank": "RB20", "tier": 3, "proj": 12.9, "rec": 2.8, "opp": "@ CLE"},
    {"name": "Kareem Hunt", "team": "KC", "pos": "RB", "ecr": 21, "pos_rank": "RB21", "tier": 3, "proj": 12.7, "rec": 2.2, "opp": "@ SF"},
    {"name": "Tank Bigsby", "team": "JAX", "pos": "RB", "ecr": 22, "pos_rank": "RB22", "tier": 4, "proj": 12.4, "rec": 1.4, "opp": "vs NE"},
    {"name": "Bucky Irving", "team": "TB", "pos": "RB", "ecr": 23, "pos_rank": "RB23", "tier": 4, "proj": 12.1, "rec": 2.8, "opp": "vs BAL"},
    {"name": "Najee Harris", "team": "PIT", "pos": "RB", "ecr": 24, "pos_rank": "RB24", "tier": 4, "proj": 11.8, "rec": 2.2, "opp": "vs NYJ"},
    {"name": "Tyrone Tracy Jr.", "team": "NYG", "pos": "RB", "ecr": 25, "pos_rank": "RB25", "tier": 4, "proj": 11.6, "rec": 3.0, "opp": "vs PHI"},
    {"name": "Alexander Mattison", "team": "LV", "pos": "RB", "ecr": 26, "pos_rank": "RB26", "tier": 4, "proj": 11.2, "rec": 2.8, "opp": "@ LAR"},
    {"name": "Rhamondre Stevenson", "team": "NE", "pos": "RB", "ecr": 28, "pos_rank": "RB28", "tier": 4, "proj": 10.6, "rec": 2.4, "opp": "@ JAX"},
    {"name": "Javonte Williams", "team": "DEN", "pos": "RB", "ecr": 29, "pos_rank": "RB29", "tier": 4, "proj": 10.3, "rec": 3.0, "opp": "@ NO"},
    {"name": "Travis Etienne Jr.", "team": "JAX", "pos": "RB", "ecr": 36, "pos_rank": "RB36", "tier": 5, "proj": 6.4, "rec": 2.0, "opp": "vs NE"},
    {"name": "Zack Moss", "team": "CIN", "pos": "RB", "ecr": 38, "pos_rank": "RB38", "tier": 5, "proj": 7.8, "rec": 2.0, "opp": "@ CLE"},

    # WRs
    {"name": "Ja'Marr Chase", "team": "CIN", "pos": "WR", "ecr": 1, "pos_rank": "WR1", "tier": 1, "proj": 17.9, "rec": 6.6, "opp": "@ CLE"},
    {"name": "Justin Jefferson", "team": "MIN", "pos": "WR", "ecr": 2, "pos_rank": "WR2", "tier": 1, "proj": 17.6, "rec": 6.4, "opp": "vs DET"},
    {"name": "Amon-Ra St. Brown", "team": "DET", "pos": "WR", "ecr": 3, "pos_rank": "WR3", "tier": 1, "proj": 16.8, "rec": 7.0, "opp": "@ MIN"},
    {"name": "A.J. Brown", "team": "PHI", "pos": "WR", "ecr": 4, "pos_rank": "WR4", "tier": 1, "proj": 16.4, "rec": 5.8, "opp": "@ NYG"},
    {"name": "Malik Nabers", "team": "NYG", "pos": "WR", "ecr": 5, "pos_rank": "WR5", "tier": 1, "proj": 15.9, "rec": 6.8, "opp": "vs PHI"},
    {"name": "Drake London", "team": "ATL", "pos": "WR", "ecr": 6, "pos_rank": "WR6", "tier": 2, "proj": 15.3, "rec": 6.0, "opp": "vs SEA"},
    {"name": "Terry McLaurin", "team": "WAS", "pos": "WR", "ecr": 7, "pos_rank": "WR7", "tier": 2, "proj": 15.0, "rec": 5.6, "opp": "vs CAR"},
    {"name": "Chris Godwin", "team": "TB", "pos": "WR", "ecr": 8, "pos_rank": "WR8", "tier": 2, "proj": 14.8, "rec": 6.2, "opp": "vs BAL"},
    {"name": "Stefon Diggs", "team": "HOU", "pos": "WR", "ecr": 9, "pos_rank": "WR9", "tier": 2, "proj": 14.5, "rec": 6.0, "opp": "@ GB"},
    {"name": "Mike Evans", "team": "TB", "pos": "WR", "ecr": 10, "pos_rank": "WR10", "tier": 2, "proj": 14.3, "rec": 4.8, "opp": "vs BAL"},
    {"name": "DK Metcalf", "team": "SEA", "pos": "WR", "ecr": 11, "pos_rank": "WR11", "tier": 2, "proj": 14.1, "rec": 5.0, "opp": "@ ATL"},
    {"name": "Garrett Wilson", "team": "NYJ", "pos": "WR", "ecr": 12, "pos_rank": "WR12", "tier": 2, "proj": 13.9, "rec": 5.8, "opp": "@ PIT"},
    {"name": "Davante Adams", "team": "NYJ", "pos": "WR", "ecr": 13, "pos_rank": "WR13", "tier": 3, "proj": 13.7, "rec": 5.6, "opp": "@ PIT"},
    {"name": "Jayden Reed", "team": "GB", "pos": "WR", "ecr": 14, "pos_rank": "WR14", "tier": 3, "proj": 13.6, "rec": 5.0, "opp": "vs HOU"},
    {"name": "Tee Higgins", "team": "CIN", "pos": "WR", "ecr": 15, "pos_rank": "WR15", "tier": 3, "proj": 13.5, "rec": 5.4, "opp": "@ CLE"},
    {"name": "Deebo Samuel Sr.", "team": "SF", "pos": "WR", "ecr": 16, "pos_rank": "WR16", "tier": 3, "proj": 13.4, "rec": 4.6, "opp": "vs KC"},
    {"name": "DeVonta Smith", "team": "PHI", "pos": "WR", "ecr": 17, "pos_rank": "WR17", "tier": 3, "proj": 13.2, "rec": 5.2, "opp": "@ NYG"},
    {"name": "Brian Thomas Jr.", "team": "JAX", "pos": "WR", "ecr": 18, "pos_rank": "WR18", "tier": 3, "proj": 13.1, "rec": 4.8, "opp": "vs NE"},
    {"name": "Zay Flowers", "team": "BAL", "pos": "WR", "ecr": 19, "pos_rank": "WR19", "tier": 3, "proj": 12.9, "rec": 5.4, "opp": "@ TB"},
    {"name": "Amari Cooper", "team": "BUF", "pos": "WR", "ecr": 20, "pos_rank": "WR20", "tier": 3, "proj": 12.6, "rec": 4.8, "opp": "vs TEN"},
    {"name": "Diontae Johnson", "team": "CAR", "pos": "WR", "ecr": 21, "pos_rank": "WR21", "tier": 3, "proj": 12.4, "rec": 5.4, "opp": "@ WAS"},
    {"name": "Tyreek Hill", "team": "MIA", "pos": "WR", "ecr": 22, "pos_rank": "WR22", "tier": 3, "proj": 12.2, "rec": 4.8, "opp": "@ IND"},
    {"name": "Tank Dell", "team": "HOU", "pos": "WR", "ecr": 23, "pos_rank": "WR23", "tier": 4, "proj": 12.0, "rec": 4.8, "opp": "@ GB"},
    {"name": "Brandon Aiyuk", "team": "SF", "pos": "WR", "ecr": 24, "pos_rank": "WR24", "tier": 4, "proj": 11.8, "rec": 4.6, "opp": "vs KC"},
    {"name": "George Pickens", "team": "PIT", "pos": "WR", "ecr": 25, "pos_rank": "WR25", "tier": 4, "proj": 11.6, "rec": 4.4, "opp": "vs NYJ"},
    {"name": "Jameson Williams", "team": "DET", "pos": "WR", "ecr": 26, "pos_rank": "WR26", "tier": 4, "proj": 11.4, "rec": 3.6, "opp": "@ MIN"},
    {"name": "Ladd McConkey", "team": "LAC", "pos": "WR", "ecr": 27, "pos_rank": "WR27", "tier": 4, "proj": 11.3, "rec": 5.0, "opp": "@ ARI"},
    {"name": "JuJu Smith-Schuster", "team": "KC", "pos": "WR", "ecr": 28, "pos_rank": "WR28", "tier": 4, "proj": 11.1, "rec": 4.8, "opp": "@ SF"},
    {"name": "Romeo Doubs", "team": "GB", "pos": "WR", "ecr": 29, "pos_rank": "WR29", "tier": 4, "proj": 10.9, "rec": 4.4, "opp": "vs HOU"},
    {"name": "Josh Downs", "team": "IND", "pos": "WR", "ecr": 30, "pos_rank": "WR30", "tier": 4, "proj": 10.7, "rec": 5.2, "opp": "vs MIA"},
    {"name": "Wan'Dale Robinson", "team": "NYG", "pos": "WR", "ecr": 31, "pos_rank": "WR31", "tier": 4, "proj": 10.5, "rec": 5.6, "opp": "vs PHI"},
    {"name": "DeAndre Hopkins", "team": "TEN", "pos": "WR", "ecr": 34, "pos_rank": "WR34", "tier": 5, "proj": 9.6, "rec": 4.0, "opp": "@ BUF"},
    {"name": "Christian Kirk", "team": "JAX", "pos": "WR", "ecr": 36, "pos_rank": "WR36", "tier": 5, "proj": 9.2, "rec": 4.2, "opp": "vs NE"},
    {"name": "CeeDee Lamb", "team": "DAL", "pos": "WR", "ecr": 45, "pos_rank": "WR45", "tier": 5, "proj": 0.0, "rec": 0.0, "opp": "BYE"},
    {"name": "DJ Moore", "team": "CHI", "pos": "WR", "ecr": 46, "pos_rank": "WR46", "tier": 5, "proj": 0.0, "rec": 0.0, "opp": "BYE"},

    # TEs
    {"name": "George Kittle", "team": "SF", "pos": "TE", "ecr": 1, "pos_rank": "TE1", "tier": 1, "proj": 12.6, "rec": 5.2, "opp": "vs KC"},
    {"name": "Brock Bowers", "team": "LV", "pos": "TE", "ecr": 2, "pos_rank": "TE2", "tier": 1, "proj": 12.3, "rec": 6.2, "opp": "@ LAR"},
    {"name": "Travis Kelce", "team": "KC", "pos": "TE", "ecr": 3, "pos_rank": "TE3", "tier": 1, "proj": 11.9, "rec": 5.8, "opp": "@ SF"},
    {"name": "Trey McBride", "team": "ARI", "pos": "TE", "ecr": 4, "pos_rank": "TE4", "tier": 1, "proj": 11.4, "rec": 5.6, "opp": "vs LAC"},
    {"name": "Sam LaPorta", "team": "DET", "pos": "TE", "ecr": 5, "pos_rank": "TE5", "tier": 2, "proj": 10.4, "rec": 4.4, "opp": "@ MIN"},
    {"name": "Evan Engram", "team": "JAX", "pos": "TE", "ecr": 6, "pos_rank": "TE6", "tier": 2, "proj": 10.2, "rec": 5.4, "opp": "vs NE"},
    {"name": "Kyle Pitts", "team": "ATL", "pos": "TE", "ecr": 7, "pos_rank": "TE7", "tier": 2, "proj": 9.8, "rec": 4.2, "opp": "vs SEA"},
    {"name": "David Njoku", "team": "CLE", "pos": "TE", "ecr": 8, "pos_rank": "TE8", "tier": 2, "proj": 9.6, "rec": 4.8, "opp": "vs CIN"},
    {"name": "Tucker Kraft", "team": "GB", "pos": "TE", "ecr": 9, "pos_rank": "TE9", "tier": 2, "proj": 9.4, "rec": 3.8, "opp": "vs HOU"},
    {"name": "Cade Otton", "team": "TB", "pos": "TE", "ecr": 10, "pos_rank": "TE10", "tier": 3, "proj": 9.1, "rec": 4.4, "opp": "vs BAL"},
    {"name": "Dalton Kincaid", "team": "BUF", "pos": "TE", "ecr": 11, "pos_rank": "TE11", "tier": 3, "proj": 8.9, "rec": 4.2, "opp": "vs TEN"},
    {"name": "Mark Andrews", "team": "BAL", "pos": "TE", "ecr": 12, "pos_rank": "TE12", "tier": 3, "proj": 8.7, "rec": 3.6, "opp": "@ TB"},
    {"name": "Hunter Henry", "team": "NE", "pos": "TE", "ecr": 13, "pos_rank": "TE13", "tier": 3, "proj": 8.4, "rec": 4.0, "opp": "@ JAX"},
    {"name": "Zach Ertz", "team": "WAS", "pos": "TE", "ecr": 14, "pos_rank": "TE14", "tier": 3, "proj": 8.1, "rec": 3.8, "opp": "vs CAR"},
    {"name": "Dallas Goedert", "team": "PHI", "pos": "TE", "ecr": 24, "pos_rank": "TE24", "tier": 5, "proj": 0.0, "rec": 0.0, "opp": "@ NYG"},

    # Ks
    {"name": "Austin Seibert", "team": "WAS", "pos": "K", "ecr": 1, "pos_rank": "K1", "tier": 1, "proj": 9.8, "rec": 0.0, "opp": "vs CAR"},
    {"name": "Chris Boswell", "team": "PIT", "pos": "K", "ecr": 2, "pos_rank": "K2", "tier": 1, "proj": 9.4, "rec": 0.0, "opp": "vs NYJ"},
    {"name": "Justin Tucker", "team": "BAL", "pos": "K", "ecr": 3, "pos_rank": "K3", "tier": 1, "proj": 9.2, "rec": 0.0, "opp": "@ TB"},
    {"name": "Ka'imi Fairbairn", "team": "HOU", "pos": "K", "ecr": 4, "pos_rank": "K4", "tier": 1, "proj": 9.0, "rec": 0.0, "opp": "@ GB"},
    {"name": "Younghoe Koo", "team": "ATL", "pos": "K", "ecr": 5, "pos_rank": "K5", "tier": 2, "proj": 8.8, "rec": 0.0, "opp": "vs SEA"},
    {"name": "Chase McLaughlin", "team": "TB", "pos": "K", "ecr": 6, "pos_rank": "K6", "tier": 2, "proj": 8.6, "rec": 0.0, "opp": "vs BAL"},
    {"name": "Tyler Bass", "team": "BUF", "pos": "K", "ecr": 7, "pos_rank": "K7", "tier": 2, "proj": 8.5, "rec": 0.0, "opp": "vs TEN"},
    {"name": "Jake Bates", "team": "DET", "pos": "K", "ecr": 8, "pos_rank": "K8", "tier": 2, "proj": 8.4, "rec": 0.0, "opp": "@ MIN"},
    {"name": "Harrison Butker", "team": "KC", "pos": "K", "ecr": 9, "pos_rank": "K9", "tier": 2, "proj": 8.2, "rec": 0.0, "opp": "@ SF"},
    {"name": "Evan McPherson", "team": "CIN", "pos": "K", "ecr": 10, "pos_rank": "K10", "tier": 3, "proj": 8.0, "rec": 0.0, "opp": "@ CLE"},
    {"name": "Will Reichard", "team": "MIN", "pos": "K", "ecr": 11, "pos_rank": "K11", "tier": 3, "proj": 7.9, "rec": 0.0, "opp": "vs DET"},
    {"name": "Brandon Aubrey", "team": "DAL", "pos": "K", "ecr": 20, "pos_rank": "K20", "tier": 5, "proj": 0.0, "rec": 0.0, "opp": "BYE"},

    # DEFs
    {"name": "Buffalo Bills", "team": "BUF", "pos": "DEF", "ecr": 1, "pos_rank": "DST1", "tier": 1, "proj": 9.8, "rec": 0.0, "opp": "vs TEN"},
    {"name": "Denver Broncos", "team": "DEN", "pos": "DEF", "ecr": 2, "pos_rank": "DST2", "tier": 1, "proj": 9.4, "rec": 0.0, "opp": "@ NO"},
    {"name": "Cincinnati Bengals", "team": "CIN", "pos": "DEF", "ecr": 3, "pos_rank": "DST3", "tier": 1, "proj": 9.1, "rec": 0.0, "opp": "@ CLE"},
    {"name": "Washington Commanders", "team": "WAS", "pos": "DEF", "ecr": 4, "pos_rank": "DST4", "tier": 1, "proj": 8.8, "rec": 0.0, "opp": "vs CAR"},
    {"name": "Pittsburgh Steelers", "team": "PIT", "pos": "DEF", "ecr": 5, "pos_rank": "DST5", "tier": 2, "proj": 8.5, "rec": 0.0, "opp": "vs NYJ"},
    {"name": "Philadelphia Eagles", "team": "PHI", "pos": "DEF", "ecr": 6, "pos_rank": "DST6", "tier": 2, "proj": 8.3, "rec": 0.0, "opp": "@ NYG"},
    {"name": "New Orleans Saints", "team": "NO", "pos": "DEF", "ecr": 7, "pos_rank": "DST7", "tier": 2, "proj": 8.1, "rec": 0.0, "opp": "vs DEN"},
    {"name": "Minnesota Vikings", "team": "MIN", "pos": "DEF", "ecr": 8, "pos_rank": "DST8", "tier": 2, "proj": 7.9, "rec": 0.0, "opp": "vs DET"},
    {"name": "Los Angeles Rams", "team": "LAR", "pos": "DEF", "ecr": 9, "pos_rank": "DST9", "tier": 2, "proj": 7.7, "rec": 0.0, "opp": "vs LV"},
    {"name": "Green Bay Packers", "team": "GB", "pos": "DEF", "ecr": 10, "pos_rank": "DST10", "tier": 3, "proj": 7.4, "rec": 0.0, "opp": "vs HOU"},
    {"name": "Baltimore Ravens", "team": "BAL", "pos": "DEF", "ecr": 11, "pos_rank": "DST11", "tier": 3, "proj": 7.1, "rec": 0.0, "opp": "@ TB"},
    {"name": "New York Jets", "team": "NYJ", "pos": "DEF", "ecr": 12, "pos_rank": "DST12", "tier": 3, "proj": 6.8, "rec": 0.0, "opp": "@ PIT"},
]


def _adjust_proj_for_scoring(base_half_ppr_proj: float, est_receptions: float, scoring_type: str) -> float:
    if base_half_ppr_proj <= 0:
        return 0.0
    if scoring_type == "ppr":
        return round(base_half_ppr_proj + (0.5 * est_receptions), 1)
    if scoring_type == "std":
        return round(max(0.0, base_half_ppr_proj - (0.5 * est_receptions)), 1)
    return round(base_half_ppr_proj, 1)


FP_ROS_SLUGS: dict[str, str] = {
    "std": "ros-overall",
    "half_ppr": "ros-half-point-ppr-overall",
    "ppr": "ros-ppr-overall",
}


def _format_kickoff_label(kickoff_ts: Any, game_status: str) -> tuple[str, bool]:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    st = (game_status or "").strip().lower()
    is_locked = st in ("closed", "complete", "final", "inprogress", "halftime", "live")
    day_time = ""
    if kickoff_ts:
        try:
            dt = datetime.fromtimestamp(int(kickoff_ts), tz=ZoneInfo("America/New_York"))
            day_time = dt.strftime("%a %-I:%M %p")
        except Exception:
            day_time = ""

    if is_locked:
        if st in ("inprogress", "halftime", "live"):
            return (f"{day_time} • Live (Locked)" if day_time else "Live (Locked)", True)
        return (f"{day_time} • Played (Locked)" if day_time else "Played (Locked)", True)
    return (day_time, False)


def _index_player_entry(index: dict[str, dict[str, Any]], entry: dict[str, Any]) -> None:
    norm_name = normalize_player_name(entry["name"], entry["pos"], entry["team"])
    norm_pos = normalize_position(entry["pos"])
    norm_team = normalize_team(entry["team"])

    if norm_team and entry.get("game_time") is not None:
        team_games = index.setdefault("__team_games__", {})
        if norm_team not in team_games or entry.get("is_locked"):
            team_games[norm_team] = {
                "game_time": entry.get("game_time", ""),
                "is_locked": bool(entry.get("is_locked", False)),
                "opp": entry.get("opp", ""),
            }

    index[f"{norm_name}|{norm_pos}|{norm_team}"] = entry
    index[f"{norm_name}|{norm_pos}"] = entry
    # Only set bare norm_name if not already claimed by a higher-ranked player at another position
    if norm_name not in index or entry.get("source") == "fantasypros_live":
        index[norm_name] = entry
    if norm_pos == "DEF" and norm_team:
        index[f"def_{norm_team.lower()}|DEF"] = entry


def _merge_ros_entry(index: dict[str, dict[str, Any]], ros_entry: dict[str, Any]) -> None:
    norm_name = normalize_player_name(ros_entry["name"], ros_entry["pos"], ros_entry["team"])
    norm_pos = normalize_position(ros_entry["pos"])
    norm_team = normalize_team(ros_entry["team"])

    keys = [
        f"{norm_name}|{norm_pos}|{norm_team}",
        f"{norm_name}|{norm_pos}",
    ]
    if norm_pos == "DEF" and norm_team:
        keys.append(f"def_{norm_team.lower()}|DEF")

    existing = None
    for k in keys:
        if k in index:
            existing = index[k]
            break

    if existing and existing.get("source") in ("fantasypros_live", "fantasypros_table"):
        existing["ros_ecr"] = ros_entry["ros_ecr"]
        existing["ros_pos_rank"] = ros_entry["ros_pos_rank"]
        return

    # Player is not in this week's active rankings (e.g., on BYE, Out, or IR for 1-2 weeks)
    # Use their ROS positional rank so we know their true rest-of-season value
    pos_num_match = re.search(r"(\d+)", ros_entry["ros_pos_rank"])
    pos_ecr = int(pos_num_match.group(1)) if pos_num_match else 99
    team_game = index.get("__team_games__", {}).get(norm_team, {})
    new_entry = {
        "name": ros_entry["name"],
        "team": norm_team,
        "pos": norm_pos,
        "ecr": pos_ecr,
        "pos_rank": ros_entry["ros_pos_rank"],
        "tier": min(5, 1 + (pos_ecr // 8)),
        "proj": 0.0,
        "opp": team_game.get("opp", ""),
        "game_time": team_game.get("game_time", ""),
        "is_locked": bool(team_game.get("is_locked", False)),
        "ros_ecr": ros_entry["ros_ecr"],
        "ros_pos_rank": ros_entry["ros_pos_rank"],
        "source": "fantasypros_ros",
    }
    _index_player_entry(index, new_entry)


def build_baseline_fp_index(scoring_type: str = "half_ppr") -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for raw in BASELINE_WEEKLY_PLAYERS:
        ecr = int(raw["ecr"])
        pos = normalize_position(raw["pos"])
        # Estimate overall ROS rank from positional ECR for offline baseline
        ros_mult = {"QB": 6, "RB": 2, "WR": 2, "TE": 5, "K": 12, "DEF": 12}.get(pos, 3)
        entry = {
            "name": raw["name"],
            "team": normalize_team(raw["team"]),
            "pos": pos,
            "ecr": ecr,
            "pos_rank": raw["pos_rank"],
            "tier": int(raw["tier"]),
            "proj": _adjust_proj_for_scoring(float(raw["proj"]), float(raw.get("rec", 0.0)), scoring_type),
            "opp": raw.get("opp", ""),
            "game_time": "",
            "is_locked": False,
            "ros_ecr": ecr * ros_mult,
            "ros_pos_rank": raw["pos_rank"],
            "source": "fantasypros_baseline",
        }
        _index_player_entry(index, entry)
    return index


def parse_fantasypros_html(html: str, pos: str) -> list[dict[str, Any]]:
    """
    Extracts player weekly ECR & projected points from FantasyPros rankings HTML.
    Supports both embedded `var ecrData = {...};` JSON and HTML table fallback.
    """
    norm_pos = normalize_position(pos)
    results: list[dict[str, Any]] = []

    match = ECR_SCRIPT_REGEX.search(html)
    if match:
        try:
            ecr_data = json.loads(match.group(1))
            players = ecr_data.get("players", [])
            for p in players:
                name = p.get("player_name") or ""
                if not name:
                    continue
                team = normalize_team(p.get("player_team_id") or "")
                ecr = int(p.get("rank_ecr") or 999)
                tier = int(p.get("tier") or 5)
                pos_rank = str(p.get("pos_rank") or f"{norm_pos}{ecr}")
                proj_raw = p.get("r2p_pts")
                try:
                    proj = round(float(proj_raw), 1) if proj_raw is not None else 0.0
                except (ValueError, TypeError):
                    proj = 0.0
                # If r2p_pts isn't populated on rankings page, estimate smoothly from positional ECR curve
                if proj <= 0.0 and ecr < 150:
                    proj = _estimate_points_from_ecr(norm_pos, ecr)
                opp = str(p.get("player_opponent") or "")
                game_time, is_locked = _format_kickoff_label(
                    p.get("player_game_kickoff_ts"),
                    str(p.get("player_game_status") or ""),
                )
                results.append(
                    {
                        "name": name,
                        "team": team,
                        "pos": norm_pos,
                        "ecr": ecr,
                        "pos_rank": pos_rank,
                        "tier": tier,
                        "proj": proj,
                        "opp": opp,
                        "game_time": game_time,
                        "is_locked": is_locked,
                        "ros_ecr": 420 + ecr,
                        "ros_pos_rank": f"{norm_pos}--",
                        "source": "fantasypros_live",
                    }
                )
            if results:
                return results
        except Exception as exc:
            logger.warning("Failed parsing ecrData JSON for %s: %s", pos, exc)

    # Fallback: parse HTML table rows if ecrData JSON wasn't found
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table#ranking-table tbody tr, table.player-table tbody tr")
    for idx, tr in enumerate(rows, start=1):
        name_el = tr.select_one("a.player-name, td.player-label a")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        ecr = idx
        results.append(
            {
                "name": name,
                "team": "",
                "pos": norm_pos,
                "ecr": ecr,
                "pos_rank": f"{norm_pos}{ecr}",
                "tier": min(5, 1 + (ecr // 8)),
                "proj": _estimate_points_from_ecr(norm_pos, ecr),
                "opp": "",
                "ros_ecr": 420 + ecr,
                "ros_pos_rank": f"{norm_pos}--",
                "source": "fantasypros_table",
            }
        )
    return results


def parse_fantasypros_ros_html(html: str) -> list[dict[str, Any]]:
    """
    Extracts Rest of Season (ROS) overall & positional ECR rankings from FantasyPros ROS HTML.
    """
    results: list[dict[str, Any]] = []
    match = ECR_SCRIPT_REGEX.search(html)
    if not match:
        return results
    try:
        ecr_data = json.loads(match.group(1))
        for p in ecr_data.get("players", []):
            name = p.get("player_name") or ""
            if not name:
                continue
            raw_pos = str(p.get("player_position_id") or p.get("player_positions") or "RB").split(",")[0].strip()
            norm_pos = normalize_position(raw_pos)
            team = normalize_team(p.get("player_team_id") or "")
            ros_ecr = int(p.get("rank_ecr") or 999)
            ros_pos_rank = str(p.get("pos_rank") or f"{norm_pos}{ros_ecr}")
            results.append(
                {
                    "name": name,
                    "team": team,
                    "pos": norm_pos,
                    "ros_ecr": ros_ecr,
                    "ros_pos_rank": ros_pos_rank,
                }
            )
    except Exception as exc:
        logger.warning("Failed parsing ROS ecrData JSON: %s", exc)
    return results


def _estimate_points_from_ecr(pos: str, ecr: int) -> float:
    norm_pos = normalize_position(pos)
    curves = {
        "QB": (24.5, 0.35, 8.0),
        "RB": (19.5, 0.28, 4.5),
        "WR": (17.8, 0.22, 4.5),
        "TE": (12.8, 0.25, 3.5),
        "K": (9.6, 0.12, 5.5),
        "DEF": (9.5, 0.15, 4.5),
    }
    top, decay, floor_val = curves.get(norm_pos, (14.0, 0.25, 4.0))
    return round(max(floor_val, top - (ecr - 1) * decay), 1)


async def fetch_fantasypros_weekly_index(
    scoring_type: str = "half_ppr",
    attempt_live: bool = True,
) -> dict[str, dict[str, Any]]:
    """
    Builds a complete lookup index of FantasyPros Weekly ECR & projections PLUS
    Rest of Season (ROS) overall & positional rankings for the requested scoring type.
    """
    scoring_key = scoring_type if scoring_type in FP_RANKING_SLUGS else "half_ppr"
    if not attempt_live:
        return build_baseline_fp_index(scoring_key)

    index: dict[str, dict[str, Any]] = {}
    slug_map = FP_RANKING_SLUGS[scoring_key]
    ros_slug = FP_ROS_SLUGS.get(scoring_key, "ros-half-point-ppr-overall")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers) as client:
        # 1. Fetch Weekly Positional ECR & Projections
        for pos, slug in slug_map.items():
            url = f"https://www.fantasypros.com/nfl/rankings/{slug}.php"
            try:
                resp = await client.get(url)
                if resp.status_code == 200 and resp.text:
                    parsed = parse_fantasypros_html(resp.text, pos)
                    for entry in parsed:
                        _index_player_entry(index, entry)
            except Exception as exc:
                logger.debug("Failed fetching FantasyPros weekly data for %s (%s): %s", pos, slug, exc)

        # 2. Fetch Rest of Season (ROS) Overall & Positional Rankings
        ros_url = f"https://www.fantasypros.com/nfl/rankings/{ros_slug}.php"
        try:
            ros_resp = await client.get(ros_url)
            if ros_resp.status_code == 200 and ros_resp.text:
                ros_entries = parse_fantasypros_ros_html(ros_resp.text)
                for ros_entry in ros_entries:
                    _merge_ros_entry(index, ros_entry)
        except Exception as exc:
            logger.debug("Failed fetching FantasyPros ROS rankings (%s): %s", ros_slug, exc)

    if not index:
        return build_baseline_fp_index(scoring_key)

    return index
