"""aimer: stands still and fires straight at the enemy's current position."""

import numpy as np

from arena.bots.common import can_cast
from arena.config import DEFAULT_CONFIG, GameConfig
from arena.sim.types import NOOP, Action, Cast, Observation


class AimerBot:
    def __init__(self, config: GameConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def reset(self, rng: np.random.Generator) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        if can_cast(obs, "bolt"):
            return Action(cast=Cast("bolt", obs.enemy.pos))
        return NOOP
