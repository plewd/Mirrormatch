"""leader: closes to bolt range, then stands still and fires at the enemy's
predicted position based on its current velocity. Contests the center heal,
grabs nearby pickups it can reach first, and throws projectile items while Bolt
is on cooldown."""

import numpy as np

from arena.bots.common import (
    blast_cast, can_cast, contested_pickup, dist, heal_move, incoming_threat, item_shot, predict_intercept,
    shield_cast, wall_block,
)
from arena.config import DEFAULT_CONFIG, GameConfig
from arena.sim.types import Action, Cast, Observation

RANGE_FRACTION = 0.85  # engage when the predicted hit point is within this share of max range
PICKUP_DETOUR = 400.0  # go for pickups we're closer to than the enemy, within this distance
SHIELD_AT = 0.3  # raise a held shield or wall when a hit is this many seconds away


class LeaderBot:
    def __init__(self, config: GameConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.engage_range = config.abilities["bolt"].range * RANGE_FRACTION

        self.walking = False

    def reset(self, rng: np.random.Generator) -> None:
        self.walking = False

    def act(self, obs: Observation) -> Action:
        aim = predict_intercept(obs, self.config)
        in_range = dist(obs.me.pos, aim) <= self.engage_range
        cast = None
        threat = incoming_threat(obs, self.config)
        block = None
        if threat is not None and threat[0] <= SHIELD_AT:
            block = shield_cast(obs) or wall_block(obs, threat[1])
        if block is not None:
            cast = block
        elif in_range and can_cast(obs, "bolt"):
            cast = Cast("bolt", aim)
        elif not can_cast(obs, "bolt"):
            cast = item_shot(obs, self.config, RANGE_FRACTION) or blast_cast(obs, self.config)

        heal = heal_move(obs, self.config)
        if heal is not None:
            self.walking = True
            return Action(move=heal, cast=cast)
        pickup = contested_pickup(obs, PICKUP_DETOUR)
        if pickup is not None:
            self.walking = True
            return Action(move=pickup, cast=cast)
        if not in_range:
            self.walking = True
            return Action(move=obs.enemy.pos, cast=cast)  # walk into range
        # Stop once on arrival. Re-sending our (possibly delayed) position every
        # decision would drag us back toward where we used to be.
        move = obs.me.pos if self.walking else None
        self.walking = False
        return Action(move=move, cast=cast)
