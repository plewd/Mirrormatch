"""Spawn positions in world coordinates. Player 1 always mirrors player 0."""

import numpy as np

from arena.config import GameConfig

Spawns = tuple[tuple[float, float], tuple[float, float]]


def default_spawns(cfg: GameConfig) -> Spawns:
    x = cfg.arena_width * 0.2
    y = cfg.arena_height * 0.5
    return (x, y), (cfg.arena_width - x, y)


def spawn_rng(game_seed: int) -> np.random.Generator:
    """Random stream 3 of a game seed (0 = sim, 1 and 2 = players)."""
    return np.random.default_rng([game_seed, 3])


def mirrored_random_spawns(cfg: GameConfig, rng: np.random.Generator) -> Spawns:
    """Player 0 anywhere in the left third; player 1 at the mirror image."""
    r = cfg.champion_radius
    x = float(rng.uniform(r, cfg.arena_width / 3))
    y = float(rng.uniform(r, cfg.arena_height - r))
    return (x, y), (cfg.arena_width - x, y)
