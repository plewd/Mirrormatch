import dataclasses
import pathlib
import time

import numpy as np

from arena.config import DEFAULT_CONFIG
from arena.sim import Action, Cast, Game, Vec2
from arena.sim.spawns import mirrored_random_spawns


def random_actions(seed: int, ticks: int) -> list[tuple[Action, Action]]:
    rng = np.random.default_rng(seed)

    def one() -> Action:
        mv = Vec2(float(rng.uniform(0, 1200)), float(rng.uniform(0, 800))) if rng.random() < 0.2 else None
        cast = Cast("bolt", Vec2(float(rng.uniform(0, 1200)), float(rng.uniform(0, 800)))) if rng.random() < 0.1 else None
        return Action(move=mv, cast=cast)

    return [(one(), one()) for _ in range(ticks)]


def play(seed: int, actions) -> dict:
    spawns = mirrored_random_spawns(DEFAULT_CONFIG, np.random.default_rng([seed, 99]))
    game = Game(DEFAULT_CONFIG, seed, spawns)
    for a0, a1 in actions:
        if game.state.done:
            break
        game.step(a0, a1)
    return dataclasses.asdict(game.state)


def test_same_seed_and_actions_give_identical_state():
    actions = random_actions(1, 1800)
    assert play(3, actions) == play(3, actions)


def test_different_actions_give_different_state():
    assert play(3, random_actions(1, 1800)) != play(3, random_actions(2, 1800))


def test_headless_speed():
    """Sim only, pre-generated actions. Target: well above 10,000 ticks/sec."""
    action_sets = [random_actions(s, 1800) for s in range(5)]
    ticks = 0
    start = time.perf_counter()
    for seed, actions in enumerate(action_sets):
        game = Game(DEFAULT_CONFIG, seed)
        for a0, a1 in actions:
            if game.state.done:
                break
            game.step(a0, a1)
            ticks += 1
    elapsed = time.perf_counter() - start
    tps = ticks / elapsed
    print(f"\nheadless sim: {tps:,.0f} ticks/sec over {ticks} ticks")
    assert tps > 10_000


def test_sim_never_imports_pygame():
    sim_dir = pathlib.Path(__file__).parent.parent / "arena" / "sim"
    for path in sim_dir.rglob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            assert not (stripped.startswith(("import pygame", "from pygame"))), path


def test_fuzz_every_ability_stays_deterministic_and_in_bounds():
    """Random play with every pickup handed out constantly: no crashes, champions
    stay in the arena, and replaying gives the same final state."""
    pool = DEFAULT_CONFIG.pickup_pool
    loadout = DEFAULT_CONFIG.loadout

    def fuzz(seed):
        rng = np.random.default_rng(seed)
        game = Game(DEFAULT_CONFIG, seed, mirrored_random_spawns(DEFAULT_CONFIG, np.random.default_rng([seed, 99])))
        r = DEFAULT_CONFIG.champion_radius
        while not game.state.done:
            actions = []
            for champ in game.state.champions:
                if champ.item is None and rng.random() < 0.05:
                    champ.item = pool[int(rng.integers(len(pool)))]
                mv = Vec2(float(rng.uniform(0, 1200)), float(rng.uniform(0, 800))) if rng.random() < 0.2 else None
                cast = None
                if rng.random() < 0.15:
                    options = loadout + ((champ.item,) if champ.item else ())
                    aid = options[int(rng.integers(len(options)))]
                    cast = Cast(aid, Vec2(float(rng.uniform(0, 1200)), float(rng.uniform(0, 800))))
                actions.append(Action(move=mv, cast=cast))
            game.step(*actions)
            for champ in game.state.champions:
                assert r - 1e-6 <= champ.x <= 1200 - r + 1e-6 and r - 1e-6 <= champ.y <= 800 - r + 1e-6
        return dataclasses.asdict(game.state)

    for seed in range(15):
        assert fuzz(seed) == fuzz(seed)
