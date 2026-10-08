"""dodger: steps perpendicular to incoming enemy projectiles, dashing when walking
is too slow and raising a held shield or wall when neither works; otherwise plays
like leader."""

import numpy as np

from arena.bots.common import can_cast, can_sidestep, dodge_target, incoming_threat, shield_cast, wall_block
from arena.bots.leader import LeaderBot
from arena.config import DEFAULT_CONFIG, GameConfig
from arena.sim.types import Action, Cast, Observation


class DodgerBot:
    def __init__(self, config: GameConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.leader = LeaderBot(config)

    def reset(self, rng: np.random.Generator) -> None:
        self.leader.reset(rng)

    def act(self, obs: Observation) -> Action:
        threat = incoming_threat(obs, self.config)
        if threat is not None:
            _, proj, offset = threat
            target = dodge_target(obs, self.config, proj, offset)
            if not can_sidestep(obs, self.config, threat):
                if obs.me.rooted <= 0.0 and can_cast(obs, "dash"):
                    if abs(target.x - obs.me.pos.x) + abs(target.y - obs.me.pos.y) > 1.0:
                        return Action(move=target, cast=Cast("dash", target))
                block = shield_cast(obs) or wall_block(obs, proj)
                if block is not None:
                    return Action(move=target, cast=block)
            return Action(move=target)  # never root ourselves mid-dodge
        return self.leader.act(obs)
