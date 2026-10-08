import pytest

from arena.sim import Action, Cast, Vec2
from conftest import LEFT, bolt_at, config_with, make_game, move, run

OFF_LINE = (960.0, 100.0)  # enemy spawn that a horizontal bolt from LEFT misses


def test_caster_is_rooted_during_cast_then_follows_move_target():
    game = make_game(spawns=(LEFT, OFF_LINE))
    cast_ticks = game.params.abilities["bolt"].cast_ticks
    champ = game.state.champions[0]

    run(game, 1, bolt_at(1100, 400))
    run(game, 1, move(LEFT[0], 700))  # issued mid-cast: stored, not acted on
    run(game, cast_ticks - 2)
    assert (champ.x, champ.y) == LEFT
    assert champ.cast is not None

    run(game, 1)  # cast fires; champion moves on the same tick
    assert champ.cast is None
    assert len(game.state.projectiles) == 1
    assert champ.y == pytest.approx(LEFT[1] + game.params.champion_speed)


def test_cooldown_gates_casts_exactly():
    game = make_game(spawns=(LEFT, OFF_LINE))
    bolt = game.params.abilities["bolt"]
    started = []
    for tick in range(200):
        had_cast = game.state.champions[0].cast is not None
        cd_before = game.state.champions[0].cooldowns["bolt"]
        run(game, 1, bolt_at(1100, 400))  # spam cast every tick
        if not had_cast and cd_before == 0:
            started.append(tick)
    assert started == [0, bolt.cooldown_ticks, 2 * bolt.cooldown_ticks, 3 * bolt.cooldown_ticks, 4 * bolt.cooldown_ticks]
    assert game.state.next_pid == 5


def test_cast_while_casting_is_ignored():
    cfg = config_with(bolt={"cooldown": 0.0, "cast_time": 0.5})
    game = make_game(spawns=(LEFT, OFF_LINE), config=cfg)
    run(game, 15, bolt_at(1100, 400))  # 15-tick cast, recast spam is ignored
    assert game.state.next_pid == 0
    run(game, 1, bolt_at(1100, 400))
    assert game.state.next_pid == 1


def test_aim_on_self_is_ignored():
    game = make_game()
    run(game, 1, bolt_at(*LEFT))
    champ = game.state.champions[0]
    assert champ.cast is None
    assert champ.cooldowns["bolt"] == 0


def test_unknown_ability_raises():
    game = make_game()
    with pytest.raises(ValueError):
        run(game, 1, Action(cast=Cast("fireball", Vec2(500, 500))))
