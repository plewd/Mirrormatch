"""idle: does nothing. A sanity check."""

import numpy as np

from arena.config import DEFAULT_CONFIG, GameConfig
from arena.sim.types import NOOP, Action, Observation


class IdleBot:
    def __init__(self, config: GameConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def reset(self, rng: np.random.Generator) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        return NOOP
