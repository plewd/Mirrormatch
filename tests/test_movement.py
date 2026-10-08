import pytest

from conftest import LEFT, make_game, move, run


def test_moves_at_constant_speed_then_snaps_and_stops():
    game = make_game()
    speed = game.params.champion_speed  # 11 units/tick
    champ = game.state.champions[0]
    target_x = LEFT[0] + 10 * speed - 5  # reachable in 10 ticks, last step is short

    run(game, 1, move(target_x, LEFT[1]))
    assert champ.x == pytest.approx(LEFT[0] + speed)
    run(game, 8)
    assert champ.x == pytest.approx(LEFT[0] + 9 * speed)
    run(game, 1, move(target_x, LEFT[1]))
    assert champ.x == pytest.approx(target_x)
    assert not champ.has_target
    run(game, 3)
    assert champ.x == pytest.approx(target_x)
    assert (champ.vx, champ.vy) == (0.0, 0.0)


def test_diagonal_speed_is_constant():
    game = make_game()
    champ = game.state.champions[0]
    run(game, 1, move(LEFT[0] + 300, LEFT[1] + 300))
    assert (champ.vx**2 + champ.vy**2) ** 0.5 == pytest.approx(game.params.champion_speed)


@pytest.mark.parametrize("target, expected", [
    ((-500.0, -500.0), (30.0, 30.0)),
    ((5000.0, 5000.0), (1170.0, 770.0)),
])
def test_cannot_leave_arena(target, expected):
    game = make_game()
    run(game, 300, move(*target))
    champ = game.state.champions[0]
    assert (champ.x, champ.y) == pytest.approx(expected)


def test_out_of_bounds_spawn_is_clamped():
    game = make_game(spawns=((-100.0, 900.0), (960.0, 400.0)))
    champ = game.state.champions[0]
    assert (champ.x, champ.y) == (30.0, 770.0)
