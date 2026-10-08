import pytest

from arena.sim.collision import segment_circle_entry
from conftest import LEFT, bolt_at, config_with, make_game, move, run


def test_travels_at_speed_and_disappears_at_max_range():
    # Enemy is off the bolt's line so nothing is hit.
    game = make_game(spawns=(LEFT, (960.0, 100.0)))
    bolt = game.params.abilities["bolt"]  # cast 8 ticks, 40 units/tick, range 900
    run(game, 1, bolt_at(1100, LEFT[1]))
    run(game, bolt.cast_ticks - 1)
    assert game.state.projectiles == []

    run(game, 1)  # cast fires, bolt spawns and moves once
    (proj,) = game.state.projectiles
    assert (proj.x, proj.y) == pytest.approx((LEFT[0] + bolt.speed, LEFT[1]))

    full_steps = int(bolt.range // bolt.speed)  # 22 moves = 880 units, still alive
    run(game, full_steps - 1)
    assert proj.traveled == pytest.approx(full_steps * bolt.speed)
    assert game.state.projectiles == [proj]
    run(game, 1)  # final partial step reaches exactly 900, then it's removed
    assert proj.traveled == pytest.approx(bolt.range)
    assert game.state.projectiles == []


def test_hits_enemy_for_one_damage_and_is_destroyed():
    game = make_game()
    run(game, 1, bolt_at(960, 400))
    run(game, 40)
    assert game.state.champions[1].hp == 2
    assert game.state.champions[0].hp == 3
    assert game.state.projectiles == []


def test_never_hits_its_owner():
    game = make_game(spawns=(LEFT, (960.0, 100.0)))
    run(game, 1, bolt_at(1100, LEFT[1]))
    run(game, 40)
    assert game.state.champions[0].hp == 3


def test_removed_when_leaving_arena():
    game = make_game(spawns=((1000.0, 400.0), (200.0, 100.0)))
    run(game, 1, bolt_at(1190, 400))
    run(game, 8 + 5)  # 5 moves of 40 units from x=1000 puts it past x=1200
    assert game.state.projectiles == []
    assert game.state.next_pid == 1


def test_fast_bolt_does_not_tunnel():
    # 100 units/tick vs. a 12-unit combined radius: sampled positions x=200, 300
    # straddle the enemy at x=250 without ever overlapping it.
    cfg = config_with(champion_radius=10.0, bolt={"speed": 3000.0, "radius": 2.0, "cast_time": 0.0})
    game = make_game(spawns=((100.0, 400.0), (250.0, 400.0)), config=cfg)
    run(game, 1, bolt_at(1000, 400))
    run(game, 1)
    assert game.state.champions[1].hp == 2


def test_hits_enemy_overlapping_spawn_point():
    cfg = config_with(bolt={"cast_time": 0.0})
    game = make_game(spawns=((500.0, 400.0), (520.0, 400.0)), config=cfg)
    run(game, 1, bolt_at(1000, 400))
    assert game.state.champions[1].hp == 2


def test_dodging_sideways_avoids_bolt():
    game = make_game()
    run(game, 1, bolt_at(960, 400), move(960, 100))
    run(game, 40, a1=move(960, 100))
    assert game.state.champions[1].hp == 3


@pytest.mark.parametrize("seg, expected", [
    ((0, 0, 9, 0), -1.0),  # stops short
    ((0, 0, 10, 0), 1.0),  # just touches at the end
    ((0, 0, 20, 0), 0.5),  # enters at x=10 of circle at 15, r=5
    ((0, 10, 20, 10), -1.0),  # passes beside
    ((14, 0, 20, 0), 0.0),  # starts inside
    ((30, 0, 40, 0), -1.0),  # moving away
])
def test_segment_circle_entry(seg, expected):
    assert segment_circle_entry(*seg, 15.0, 0.0, 5.0) == pytest.approx(expected)
