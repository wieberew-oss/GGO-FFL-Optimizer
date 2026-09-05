"""
csv_loader.py
-------------
Reads a DraftKings player-pool CSV and returns a list of Player objects.

Expected columns (from actual DK export):
    Position, Name + ID, Name, ID, Roster Position, Salary,
    Game Info, TeamAbbrev, AvgPointsPerGame, Status
"""

import io
import re
from typing import Union

import pandas as pd
import requests

from models.player import Player

# Canonical column names we depend on
REQUIRED_COLUMNS = {
    "Position",
    "Name",
    "ID",
    "Roster Position",
    "Salary",
    "Game Info",
    "TeamAbbrev",
    "AvgPointsPerGame",
}


def _parse_opponent(game_info: str, team: str) -> str:
    """
    Extract the opponent abbreviation from a Game Info string.
    Format: 'AWAY@HOME MM/DD/YYYY HH:MMam ET'
    """
    try:
        matchup = game_info.split()[0]          # e.g. 'BUF@HOU'
        away, home = matchup.split("@")
        return home if team == away else away
    except Exception:
        return ""


def _parse_roster_slots(roster_position: str) -> list:
    """
    Convert DK 'Roster Position' string to a list of eligible slots.
    Examples:
        'RB/FLEX'  -> ['RB', 'FLEX']
        'QB'       -> ['QB']
        'DST'      -> ['DST']
        'TE/FLEX'  -> ['TE', 'FLEX']
        'WR/FLEX'  -> ['WR', 'FLEX']
    """
    return [s.strip() for s in roster_position.split("/")]


def _validate_columns(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"CSV is missing expected columns: {sorted(missing)}\n"
            f"Found columns: {list(df.columns)}"
        )


def load_from_dataframe(df: pd.DataFrame) -> list:
    """Parse an already-loaded DataFrame into a list of Player objects."""
    _validate_columns(df)

    players = []
    for _, row in df.iterrows():
        try:
            name = str(row["Name"]).strip()
            dk_id = int(row["ID"])
            position = str(row["Position"]).strip()
            roster_slots = _parse_roster_slots(str(row["Roster Position"]).strip())
            salary = int(row["Salary"])
            team = str(row["TeamAbbrev"]).strip()
            game_info = str(row["Game Info"]).strip()
            opponent = _parse_opponent(game_info, team)

            # AvgPointsPerGame may be empty for bench players
            raw_proj = row["AvgPointsPerGame"]
            try:
                projection = float(raw_proj)
            except (ValueError, TypeError):
                projection = 0.0

            status = str(row.get("Status", "")).strip()
            if status.lower() == "nan":
                status = ""

            player = Player(
                name=name,
                dk_id=dk_id,
                position=position,
                roster_slots=roster_slots,
                salary=salary,
                team=team,
                opponent=opponent,
                game_info=game_info,
                projection=projection,
                status=status,
            )
            players.append(player)
        except Exception as e:
            # Skip malformed rows but don't crash the whole load
            continue

    return players


def load_from_file(filepath: str) -> list:
    """Load players from a CSV file path."""
    df = pd.read_csv(filepath)
    return load_from_dataframe(df)


def load_from_upload(uploaded_file) -> list:
    """Load players from a Streamlit UploadedFile object."""
    df = pd.read_csv(uploaded_file)
    return load_from_dataframe(df)


def load_from_url(url: str, timeout: int = 10) -> tuple:
    """
    Attempt to fetch the DK player CSV from a URL.
    Returns (players, error_message).
    If successful, error_message is None.
    If failed, players is None and error_message explains why.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        players = load_from_dataframe(df)
        return players, None
    except requests.exceptions.HTTPError as e:
        return None, f"HTTP error fetching CSV: {e}"
    except requests.exceptions.ConnectionError:
        return None, "Could not connect to DraftKings. Check your network connection."
    except requests.exceptions.Timeout:
        return None, "Request timed out fetching the DraftKings CSV."
    except Exception as e:
        return None, f"Unexpected error: {e}"
