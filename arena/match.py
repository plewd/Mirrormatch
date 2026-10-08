"""Run one game between two controllers."""

from dataclasses import dataclass

import numpy as np

from arena.config import DEFAULT_CONFIG, GameConfig
from arena.controller import Controller
from arena.sim.game import Game
from arena.sim.spawns import Spawns


@dataclass(frozen=True)
class MatchResult:
    winner: int | None  # None = draw
    ticks: int
    hp: tuple[int, int]


def controller_rng(game_seed: int, player: int) -> np.random.Generator:
    """Stream 0 belongs to the sim; players get streams 1 and 2."""
    return np.random.default_rng([game_seed, 1 + player])


def run_match(
    c0: Controller,
    c1: Controller,
    config: GameConfig = DEFAULT_CONFIG,
    seed: int = 0,
    spawns: Spawns | None = None,
) -> MatchResult:
    game = Game(config, seed, spawns)
    c0.reset(controller_rng(seed, 0))
    c1.reset(controller_rng(seed, 1))
    state = game.state
    while not state.done:
        game.step(c0.act(game.observe(0)), c1.act(game.observe(1)))
    return MatchResult(
        winner=state.winner,
        ticks=state.tick,
        hp=(state.champions[0].hp, state.champions[1].hp),
    )
