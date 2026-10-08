"""random: wanders to random points and casts at random points."""

import numpy as np

from arena.bots.common import can_cast
from arena.config import DEFAULT_CONFIG, GameConfig
from arena.sim.types import Action, Cast, Observation, Vec2

MOVE_PROB = 0.1  # per decision
CAST_PROB = 0.1


class RandomBot:
    def __init__(self, config: GameConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.rng = np.random.default_rng(0)

    def reset(self, rng: np.random.Generator) -> None:
        self.rng = rng

    def _point(self) -> Vec2:
        c = self.config
        return Vec2(float(self.rng.uniform(0, c.arena_width)), float(self.rng.uniform(0, c.arena_height)))

    def act(self, obs: Observation) -> Action:
        move = self._point() if self.rng.random() < MOVE_PROB else None
        cast = None
        if can_cast(obs, "bolt") and self.rng.random() < CAST_PROB:
            cast = Cast("bolt", self._point())
        return Action(move=move, cast=cast)
