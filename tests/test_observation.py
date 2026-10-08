import numpy as np
import pytest

from arena.config import DEFAULT_CONFIG

from arena.sim import Action, Cast, Vec2
from conftest import LEFT, RIGHT, bolt_at, make_game, move, run


def random_canonical_action(rng: np.random.Generator) -> Action:
    mv = Vec2(float(rng.uniform(0, 1200)), float(rng.uniform(0, 800))) if rng.random() < 0.3 else None
    cast = Cast("bolt", Vec2(float(rng.uniform(0, 1200)), float(rng.uniform(0, 800)))) if rng.random() < 0.1 else None
    return Action(move=mv, cast=cast)


def champ_tuple(c):
    return (c.pos.x, c.pos.y, c.vel.x, c.vel.y, c.hp, c.cooldowns["bolt"], c.cast_ability, c.cast_remaining)


def projectile_tuples(obs):
    # Spawn order differs per side (player 0's projectile is listed first for both), so sort.
    return sorted((p.is_own, p.pos.x, p.pos.y, p.vel.x, p.vel.y) for p in obs.projectiles)


def assert_mirror_equal(o0, o1):
    """Mirrored float math (W - x) isn't bit-exact, so compare approximately."""
    assert champ_tuple(o0.me) == pytest.approx(champ_tuple(o1.me))
    assert champ_tuple(o0.enemy) == pytest.approx(champ_tuple(o1.enemy))
    assert len(o0.projectiles) == len(o1.projectiles)
    for a, b in zip(projectile_tuples(o0), projectile_tuples(o1)):
        assert a == pytest.approx(b)
    assert o0.time_remaining == o1.time_remaining


def test_both_players_see_themselves_on_the_left():
    game = make_game()
    for player in (0, 1):
        obs = game.observe(player)
        assert obs.me.pos == Vec2(*LEFT)
        assert obs.enemy.pos == Vec2(*RIGHT)


def test_identical_canonical_actions_give_identical_observations():
    """With mirrored spawns, feeding both players the same canonical action keeps
    the game perfectly mirror-symmetric, so both observations stay identical."""
    game = make_game()
    rng = np.random.default_rng(7)
    for _ in range(300):
        a = random_canonical_action(rng)
        game.step(a, a)
        assert_mirror_equal(game.observe(0), game.observe(1))
        if game.state.done:
            break
    c0, c1 = game.state.champions
    assert c1.x == pytest.approx(1200 - c0.x) and c1.y == pytest.approx(c0.y)


def test_actions_are_unmirrored_for_right_player():
    game = make_game()
    run(game, 1, a1=move(LEFT[0], 100))  # canonical "straight up" for player 1
    c1 = game.state.champions[1]
    assert c1.target_x == RIGHT[0] and c1.target_y == 100


def test_velocities_in_units_per_second_and_mirrored():
    game = make_game()
    run(game, 1, move(1100, 400), move(1100, 400))  # both run toward the enemy
    for player in (0, 1):
        obs = game.observe(player)
        assert obs.me.vel.x == pytest.approx(DEFAULT_CONFIG.champion_speed)
        assert obs.enemy.vel.x == pytest.approx(-DEFAULT_CONFIG.champion_speed)


def test_projectile_view_and_cooldowns():
    game = make_game(spawns=(LEFT, (960.0, 100.0)))
    run(game, 1, bolt_at(1100, 400))
    obs0 = game.observe(0)
    assert obs0.me.cast_ability == "bolt"
    assert obs0.me.cooldowns["bolt"] == pytest.approx(44 / 30)
    run(game, 8)
    obs0, obs1 = game.observe(0), game.observe(1)
    (p0,), (p1,) = obs0.projectiles, obs1.projectiles
    assert p0.is_own and not p1.is_own
    assert p0.vel.x == pytest.approx(1200.0) and p1.vel.x == pytest.approx(-1200.0)
    assert p1.pos.x == pytest.approx(1200 - p0.pos.x)
    assert obs0.time_remaining == pytest.approx(90 - 9 / 30)
