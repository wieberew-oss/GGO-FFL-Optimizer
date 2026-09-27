from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from data.nflverse import get_game_context
from models.player import Player
from models.projections import PlayerStats, projection_math
from optimization.optimizer import optimize


class ProjectionFlowTests(unittest.TestCase):
    def test_projection_math_explains_qb_blend_and_adjustments(self):
        player = Player(
            name="QB",
            dk_id=1,
            position="QB",
            roster_slots=["QB"],
            salary=8000,
            team="BUF",
            opponent="LAC",
            game_info="BUF@LAC 09/27/2026 1:00PM ET",
            projection=39.7,
            status="",
        )
        stats = PlayerStats(
            recent_fantasy_pts=20.6,
            implied_total=21.8,
            is_home=True,
            adjusted_projection=28.3,
        )

        description = projection_math(player, stats, matchup_multiplier=1.1)

        self.assertIn("DK 39.7 x 40%", description)
        self.assertIn("recent 20.6 x 60%", description)
        self.assertIn("Vegas -0.3", description)
        self.assertIn("home +0.4", description)
        self.assertIn("x defense 1.10 = 31.1", description)

    def test_game_context_matches_slate_date(self):
        schedules = pd.DataFrame([
            {
                "season": 2025,
                "week": 4,
                "home_team": "HOU",
                "away_team": "BUF",
                "gameday": "2025-09-28",
                "total_line": 42.0,
                "spread_line": 2.0,
            },
            {
                "season": 2026,
                "week": 4,
                "home_team": "HOU",
                "away_team": "BUF",
                "gameday": "2026-09-27",
                "total_line": 48.0,
                "spread_line": 4.0,
            },
        ])

        with patch("data.nflverse.fetch_schedules", return_value=schedules):
            context = get_game_context([2026], "BUF", "HOU", date(2026, 9, 27))

        self.assertEqual(context["total_line"], 48.0)

    def test_optimizer_total_uses_enriched_and_matchup_projection(self):
        positions = [
            ("QB", "QB"),
            ("RB", "RB/FLEX"), ("RB", "RB/FLEX"), ("RB", "RB/FLEX"),
            ("WR", "WR/FLEX"), ("WR", "WR/FLEX"), ("WR", "WR/FLEX"),
            ("TE", "TE/FLEX"), ("DST", "DST"),
        ]
        players = [
            Player(
                name=f"Player {index}",
                dk_id=index,
                position=position,
                roster_slots=slots.split("/"),
                salary=5000,
                team="BUF",
                opponent="HOU",
                game_info="BUF@HOU 09/27/2026 1:00PM ET",
                projection=10.0,
                status="",
            )
            for index, (position, slots) in enumerate(positions, start=1)
        ]

        result = optimize(
            players,
            exclude_injured=False,
            enriched_stats={
                1: SimpleNamespace(
                    adjusted_projection=20.0,
                    data_source="enriched",
                    vegas_adjustment=0.4,
                )
            },
            matchup_multipliers={1: 1.1},
        )

        self.assertTrue(result.feasible, result.message)
        self.assertEqual(result.total_projection, 102.0)
        self.assertEqual(result.to_display_rows()[0]["Proj"], "22.0")
        self.assertEqual(result.to_display_rows()[0]["Vegas Δ"], "+0.4")
        self.assertEqual(result.to_display_rows()[0]["Defense Δ"], "+2.0")

    def test_dk_only_mode_ignores_all_adjustments(self):
        positions = [
            ("QB", "QB"),
            ("RB", "RB/FLEX"), ("RB", "RB/FLEX"), ("RB", "RB/FLEX"),
            ("WR", "WR/FLEX"), ("WR", "WR/FLEX"), ("WR", "WR/FLEX"),
            ("TE", "TE/FLEX"), ("DST", "DST"),
        ]
        players = [
            Player(
                name=f"Player {index}",
                dk_id=index,
                position=position,
                roster_slots=slots.split("/"),
                salary=5000,
                team="BUF",
                opponent="HOU",
                game_info="BUF@HOU 09/27/2026 1:00PM ET",
                projection=10.0,
                status="",
            )
            for index, (position, slots) in enumerate(positions, start=1)
        ]

        result = optimize(
            players,
            exclude_injured=False,
            enriched_stats={1: SimpleNamespace(adjusted_projection=20.0)},
            matchup_multipliers={1: 1.5},
            projection_mode="dk_only",
        )

        self.assertTrue(result.feasible, result.message)
        self.assertEqual(result.total_projection, 90.0)
        self.assertEqual(result.to_display_rows()[0]["Proj"], "10.0")
        self.assertEqual(result.to_display_rows()[0]["Vegas Δ"], "Not applied")
        self.assertEqual(result.to_display_rows()[0]["Defense Δ"], "Not applied")


if __name__ == "__main__":
    unittest.main()