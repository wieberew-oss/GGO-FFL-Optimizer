from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Player:
    """Normalized internal representation of a DraftKings player."""

    name: str
    dk_id: int
    position: str          # Primary DK position: QB, RB, WR, TE, DST
    roster_slots: list     # Eligible slots, e.g. ["RB", "FLEX"]
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
        # Compute value (pts per $1000 of salary) whenever projection is set
        if self.salary and self.salary > 0:
            self.value = round(self.projection / (self.salary / 1000), 3)
        else:
            self.value = 0.0

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

    def to_dict(self) -> dict:
        return {
            "Name": self.name,
            "Position": self.position,
            "Team": self.team,
            "Opponent": self.opponent,
            "Salary": self.salary,
            "Projection": self.projection,
            "Value": self.value,
            "Status": self.status if self.status else "OK",
            "Slots": "/".join(self.roster_slots),
        }
