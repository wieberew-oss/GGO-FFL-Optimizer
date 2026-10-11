from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Player:
    """Normalized internal representation of a DraftKings player."""

    name: str
    dk_id: int
    position: str          # Primary DK position: QB, RB, WR, TE, DST
    roster_slots: List[str]  # Eligible slots, e.g. ["RB", "FLEX"]
    salary: int
    team: str
    opponent: str          # Derived from Game Info
    game_info: str         # Raw game info string
    projection: float      # AvgPointsPerGame used as projection seed
    status: str            # "", "Q", "OUT", "IR"

    # Derived / enriched fields (populated later)
    floor: Optional[float] = None
    ceiling: Optional[float] = None
    value: Optional[float] = field(default=None)

    def __post_init__(self):
        self._recompute_value()

    def _recompute_value(self) -> None:
        if self.salary and self.salary > 0:
            self.value = round(self.projection / (self.salary / 1000), 3)
        else:
            self.value = 0.0

    def update_projection(self, new_proj: float) -> None:
        """Update projection and recompute value."""
        self.projection = new_proj
        self._recompute_value()

    @property
    def is_available(self) -> bool:
        """True if the player is not on IR or OUT."""
        return self.status not in ("OUT", "IR")

    @property
    def is_healthy(self) -> bool:
        """True if the player has no injury designation."""
        return self.status == ""

    def can_play_slot(self, slot: str) -> bool:
        """Check whether this player is eligible for a given roster slot."""
        return slot in self.roster_slots

    @property
    def game_key(self) -> str:
        """Short matchup key used for the multi-game constraint (e.g. 'DET@ARI')."""
        if not self.game_info:
            return self.team or "UNK"
        return self.game_info.split()[0]

    def to_dict(self) -> dict:
        return {
            "Name": self.name,
            "Position": self.position,
            "Team": self.team,
            "Opponent": self.opponent,
            "Salary": self.salary,
            "Projection": self.projection,
            "Floor": self.floor,
            "Ceiling": self.ceiling,
            "Value": self.value,
            "Status": self.status if self.status else "OK",
            "Slots": "/".join(self.roster_slots),
            "Game": self.game_key,
        }
