import pytest

from conftest import bolt_at, config_with, make_game, run


def test_timeout_with_equal_hp_is_a_draw():
    game = make_game()
    while not game.state.done:
        run(game, 1)
    assert game.state.tick == game.params.time_limit_ticks == 2700
    assert game.state.winner is None


def test_timeout_goes_to_more_hp():
    game = make_game(config=config_with(time_limit=3.0))
    run(game, 1, bolt_at(960, 400))
    while not game.state.done:
        run(game, 1)
    assert game.state.tick == 90
    assert [c.hp for c in game.state.champions] == [3, 2]
    assert game.state.winner == 0


def test_kill_wins():
    game = make_game(config=config_with(champion_hp=1))
    run(game, 1, bolt_at(960, 400))
    while not game.state.done:
        run(game, 1)
    assert game.state.winner == 0
    assert game.state.champions[1].hp == 0
    assert game.state.tick < 60


def test_simultaneous_kill_is_a_draw():
    # Player 1 aims at its mirrored-frame enemy position, which is the same canonical point.
    game = make_game(config=config_with(champion_hp=1))
    run(game, 1, bolt_at(960, 400), bolt_at(960, 400))
    while not game.state.done:
        run(game, 1)
    assert game.state.winner is None
    assert [c.hp for c in game.state.champions] == [0, 0]


def test_step_after_end_raises():
    game = make_game(config=config_with(time_limit=0.1))
    run(game, 3)
    assert game.state.done
    with pytest.raises(RuntimeError):
        run(game, 1)
