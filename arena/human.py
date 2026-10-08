"""Human player as a Controller. The pygame front end feeds it commands in the
human's canonical frame; it hands them to the sim on the next tick."""

import numpy as np

from arena.sim.types import Action, Cast, Observation, Vec2


class HumanController:
    def __init__(self) -> None:
        self.pending_move: Vec2 | None = None
        self.pending_cast: Cast | None = None

    def reset(self, rng: np.random.Generator) -> None:
        self.pending_move = None
        self.pending_cast = None

    def command_move(self, target: Vec2) -> None:
        self.pending_move = target

    def command_cast(self, ability_id: str, aim: Vec2) -> None:
        self.pending_cast = Cast(ability_id, aim)

    def act(self, obs: Observation) -> Action:
        action = Action(move=self.pending_move, cast=self.pending_cast)
        self.pending_move = None
        self.pending_cast = None
        return action
