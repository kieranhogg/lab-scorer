"""Turn the saved lab progress into points.

A step earns its `points` from the lab file once the student passes it.
Each hint request on a step costs HINT_PENALTY of those points, up to MAX_HINT_PENALTY.
The cap keeps a passed step worth at least half, so asking for help never feels pointless.
"""
from labtools.state import read_hint_counts, read_passed

HINT_PENALTY = 0.10
MAX_HINT_PENALTY = 0.50


def step_score(points: float, hints: int) -> int:
    """Return the points a passed step earns after the hint penalty."""
    penalty = min(hints * HINT_PENALTY, MAX_HINT_PENALTY)
    return round(points * (1 - penalty))


def compute_score(steps: list[dict]) -> tuple[int, int]:
    """Return (earned, total) points across the lab steps."""
    passed = read_passed()
    hints = read_hint_counts()
    earned = total = 0
    for number, step in enumerate(steps):
        points = step.get("points", 0)
        total += points
        if number in passed:
            earned += step_score(points, hints.get(number, 0))
    return round(earned), round(total)
