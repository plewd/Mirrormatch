import math

import numpy as np
import pytest

from arena.config import DEFAULT_CONFIG, Difficulty
from arena.fairness import FairController
from arena.sim import NOOP, Action, Cast, Vec2
from conftest import make_game, run


class Recorder:
    """Records every observation it's given; casts at a fixed point when asked."""

    def __init__(self, action: Action = NOOP) -> None:
        self.action = action
        self.seen = []

    def reset(self, rng):
        self.seen = []

    def act(self, obs):
        self.seen.append(obs)
        return self.action


def drive(fair: FairController, ticks: int) -> list[Action]:
    game = make_game()
    fair.reset(np.random.default_rng(0))
    actions = []
    for _ in range(ticks):
        a = fair.act(game.observe(0))
        actions.append(a)
        game.step(NOOP, NOOP)
    return actions


def test_reaction_delay():
    inner = Recorder()
    fair = FairController(inner, Difficulty(reaction_delay=4, rate_limit=1, aim_noise_deg=0))
    drive(fair, 10)
    seen_ticks = [round((DEFAULT_CONFIG.time_limit - o.time_remaining) * 30) for o in inner.seen]
    # Ticks 0..4 all see tick 0; afterwards the bot lags 4 ticks.
    assert seen_ticks == [0, 0, 0, 0, 0, 1, 2, 3, 4, 5]


def test_rate_limit():
    cast = Action(move=Vec2(500, 500), cast=Cast("bolt", Vec2(900, 400)))
    inner = Recorder(cast)
    fair = FairController(inner, Difficulty(reaction_delay=0, rate_limit=3, aim_noise_deg=0))
    actions = drive(fair, 9)
    assert len(inner.seen) == 3
    assert [a is NOOP for a in actions] == [False, True, True] * 3


def test_aim_noise_rotates_about_bot_and_is_seeded():
    cast = Action(cast=Cast("bolt", Vec2(940, 400)))  # 700 units right of LEFT spawn
    def angles(seed):
        fair = FairController(Recorder(cast), Difficulty(reaction_delay=0, rate_limit=1, aim_noise_deg=5.0))
        game = make_game()
        fair.reset(np.random.default_rng(seed))
        out = []
        for _ in range(200):
            aim = fair.act(game.observe(0)).cast.aim
            assert math.hypot(aim.x - 240, aim.y - 400) == pytest.approx(700)
            out.append(math.degrees(math.atan2(aim.y - 400, aim.x - 240)))
        return out
    a = angles(1)
    assert a == angles(1)
    assert a != angles(2)
    assert 3.5 < np.std(a) < 6.5
