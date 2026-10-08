"""Wraps any controller with reaction delay, an action rate limit, and aim noise."""

import math
from collections import deque

import numpy as np

from arena.config import Difficulty
from arena.controller import Controller
from arena.sim.types import NOOP, Action, Cast, Observation, Vec2


def rotate_about(point: Vec2, center: Vec2, angle: float) -> Vec2:
    c = math.cos(angle)
    s = math.sin(angle)
    dx = point.x - center.x
    dy = point.y - center.y
    return Vec2(center.x + dx * c - dy * s, center.y + dx * s + dy * c)


def add_aim_noise(action: Action, origin: Vec2, std_deg: float, rng: np.random.Generator) -> Action:
    """Rotate the cast's aim point about `origin` by a Gaussian angle."""
    if action.cast is None or std_deg <= 0.0:
        return action
    angle = math.radians(float(rng.normal(0.0, std_deg)))
    aim = rotate_about(action.cast.aim, origin, angle)
    return Action(move=action.move, cast=Cast(action.cast.ability_id, aim))


class DelayBuffer:
    """Returns the observation from `delay` ticks ago (the first one, early on)."""

    def __init__(self, delay: int) -> None:
        self.history: deque[Observation] = deque(maxlen=delay + 1)

    def clear(self) -> None:
        self.history.clear()

    def push(self, obs: Observation) -> Observation:
        self.history.append(obs)
        return self.history[0]


class FairController:
    def __init__(self, inner: Controller, difficulty: Difficulty) -> None:
        self.inner = inner
        self.difficulty = difficulty
        self.delay = DelayBuffer(difficulty.reaction_delay)
        self.rng = np.random.default_rng(0)
        self.tick = 0
        self.last_action: Action = NOOP  # most recent decision (for the debugger)
        self.last_seen: Observation | None = None  # the delayed observation it was made from (for the debugger)

    def reset(self, rng: np.random.Generator) -> None:
        self.rng = rng
        # The inner bot gets its own stream derived from ours, so noise draws don't shift it.
        self.inner.reset(np.random.default_rng(rng.integers(2**63)))
        self.delay.clear()
        self.tick = 0
        self.last_action = NOOP
        self.last_seen = None

    def act(self, obs: Observation) -> Action:
        seen = self.delay.push(obs)
        decide = self.tick % self.difficulty.rate_limit == 0
        self.tick += 1
        if not decide:
            return NOOP  # the sim keeps the last move target; casts are not repeated
        action = self.inner.act(seen)
        self.last_action = action
        self.last_seen = seen
        return add_aim_noise(action, seen.me.pos, self.difficulty.aim_noise_deg, self.rng)
