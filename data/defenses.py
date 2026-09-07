# ===========================================================================
# File: data/defenses.py
# ===========================================================================
"""
defenses.py
-----------
Diagnostic version to verify file path resolution and JSON loading.
"""

import os
import json

_DEFENSE_CACHE = None

ABBR_TO_FULL_NAME = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LV": "Las Vegas Raiders", "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SF": "San Francisco 49ers", "SEA": "Seattle Seahawks", "TB": "Tampa Bank Buccaneers",
    "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}


def load_defensive_predictions():
    global _DEFENSE_CACHE
    if _DEFENSE_CACHE is not None:
        return _DEFENSE_CACHE

    # Construct absolute path relative to this defenses.py file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(current_dir, "Defense_Predictions.json")

    print(f"DEBUG: Looking for JSON at -> {json_path}")
    print(f"DEBUG: File exists? -> {os.path.exists(json_path)}")

    if not os.path.exists(json_path):
        _DEFENSE_CACHE = {}
        return _DEFENSE_CACHE

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            cache = {}
            if isinstance(data, list):
                for item in data:
                    team_name = item.get("team")
                    if team_name:
                        cache[team_name.lower()] = item
            elif isinstance(data, dict):
                for k, v in data.items():
                    cache[k.lower()] = v
            _DEFENSE_CACHE = cache
            print(f"DEBUG: Successfully loaded {_DEFENSE_CACHE.keys()} teams from JSON!")
    except Exception as e:
        print(f"DEBUG: Error loading JSON: {e}")
        _DEFENSE_CACHE = {}

    return _DEFENSE_CACHE


def _tier_to_multiplier(text: str) -> float:
    if not text:
        return 1.0
    t = text.lower()
    if "elite" in t or "top 3" in t or "shutdown" in t:
        return 0.88
    elif "above average" in t or "solid" in t:
        return 0.94
    elif "vulnerable" in t or "poor" in t or "bottom" in t or "matador" in t:
        return 1.10
    elif "weak" in t:
        return 1.08
    return 1.0


def get_opponent_defensive_factor(position: str, opponent: str, use_preseason: bool = True) -> float:
    if not use_preseason or not opponent:
        return 1.0

    defenses = load_defensive_predictions()

    opp_upper = opponent.upper()
    full_name = ABBR_TO_FULL_NAME.get(opp_upper, "")

    def_data = None
    if full_name:
        def_data = defenses.get(full_name.lower())

    if not def_data:
        for json_team_name, data_dict in defenses.items():
            if opp_upper in json_team_name.upper() or opponent.lower() in json_team_name.lower():
                def_data = data_dict
                break

    if not def_data:
        return 1.0

    if position == "RB":
        proj_text = def_data.get("vs_run_projection", "")
    else:
        proj_text = def_data.get("vs_pass_projection", "")

    multiplier = _tier_to_multiplier(proj_text)

    if multiplier == 1.0 and "rank" in def_data:
        rank = def_data.get("rank", 16)
        multiplier = 1.0 + ((16.5 - rank) / 100.0)

    return max(0.85, min(1.15, multiplier))