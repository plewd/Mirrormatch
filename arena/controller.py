"""The interface every player goes through: human, scripted bot, or trained policy."""

from typing import Protocol

import numpy as np

from arena.sim.types import Action, Observation


class Controller(Protocol):
    def reset(self, rng: np.random.Generator) -> None:
        """Called before each game with this controller's own seeded random stream."""
        ...

    def act(self, obs: Observation) -> Action:
        """Called once per tick with an observation in this player's canonical frame."""
        ...
