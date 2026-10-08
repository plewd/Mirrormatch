from dataclasses import replace

from arena.config import BOLT, DEFAULT_CONFIG, GameConfig
from arena.sim import NOOP, Action, Cast, Game, Vec2

LEFT = (240.0, 400.0)
RIGHT = (960.0, 400.0)


def make_game(spawns=(LEFT, RIGHT), config: GameConfig = DEFAULT_CONFIG, seed: int = 0) -> Game:
    return Game(config, seed, spawns)


def config_with(bolt: dict | None = None, **overrides) -> GameConfig:
    """DEFAULT_CONFIG with game-level overrides and optional Bolt stat overrides."""
    cfg = replace(DEFAULT_CONFIG, **overrides)
    if bolt:
        cfg = replace(cfg, abilities={**cfg.abilities, "bolt": replace(BOLT, **bolt)})
    return cfg


def run(game: Game, ticks: int, a0: Action = NOOP, a1: Action = NOOP) -> None:
    for _ in range(ticks):
        game.step(a0, a1)


def move(x: float, y: float) -> Action:
    return Action(move=Vec2(x, y))


def bolt_at(x: float, y: float) -> Action:
    return Action(cast=Cast("bolt", Vec2(x, y)))
