import math

import pytest

from arena.sim import Action, Cast, Vec2
from arena.sim.collision import segment_box_exit, segment_capsule_entry
from conftest import LEFT, bolt_at, make_game, move, run

OFF_LINE = (960.0, 100.0)


def dash_at(x, y):
    return Action(cast=Cast("dash", Vec2(x, y)))


def test_dash_covers_exact_distance_quickly_then_stops():
    game = make_game(spawns=(LEFT, OFF_LINE))
    me = game.state.champions[0]
    run(game, 1, Action(move=Vec2(1100, 400), cast=Cast("dash", Vec2(240, 700))))  # dash straight down
    assert me.forced is not None
    run(game, 4)  # 250 units at ~55.6/tick = 5 ticks in total
    assert (me.x, me.y) == pytest.approx((240.0, 650.0))
    assert me.forced is None
    run(game, 3)
    assert (me.x, me.y) == pytest.approx((240.0, 650.0))  # move target was cleared by the dash


def test_dash_stops_at_arena_edge():
    game = make_game(spawns=((240.0, 700.0), OFF_LINE))
    me = game.state.champions[0]
    run(game, 1, dash_at(240, 790))
    run(game, 1)
    assert me.y == pytest.approx(770.0) and me.forced is None


def test_no_casting_while_dashing_and_dash_cooldown():
    game = make_game(spawns=(LEFT, OFF_LINE))
    me = game.state.champions[0]
    run(game, 1, dash_at(240, 700))
    run(game, 1, bolt_at(1100, 400))  # mid-dash: ignored
    assert me.cast is None and me.cooldowns["bolt"] == 0
    assert me.cooldowns["dash"] == game.params.abilities["dash"].cooldown_ticks - 2
    run(game, 10)
    run(game, 1, dash_at(240, 100))  # still on cooldown
    assert me.forced is None


def test_no_dash_while_casting():
    game = make_game(spawns=(LEFT, OFF_LINE))
    run(game, 1, bolt_at(1100, 400))
    run(game, 1, dash_at(240, 700))
    me = game.state.champions[0]
    assert me.forced is None and me.cooldowns["dash"] == 0


def test_root_blocks_moving_and_dashing_but_not_casting():
    game = make_game(spawns=(LEFT, OFF_LINE))
    me = game.state.champions[0]
    game.state.root(0, 10)
    run(game, 1, move(600, 400))
    run(game, 1, dash_at(240, 700))
    assert (me.x, me.y) == LEFT and me.forced is None
    run(game, 1, bolt_at(1100, 400))
    assert me.cast is not None
    assert game.observe(0).me.rooted == pytest.approx(7 / 30)
    run(game, 20)  # root and cast both over; resumes walking to the stored target
    assert me.x > LEFT[0]


def test_shield_blocks_one_hit_and_is_consumed():
    game = make_game()
    game.state.shield(1, 300)
    run(game, 1, bolt_at(960, 400))
    run(game, 40)
    enemy = game.state.champions[1]
    assert enemy.hp == 3 and enemy.shield_ticks == 0 and game.state.projectiles == []
    run(game, 10, bolt_at(960, 400))  # next bolt (once off cooldown) lands
    run(game, 30)
    assert enemy.hp == 2


def test_interrupt_cancels_cast_and_keeps_cooldown_spent():
    game = make_game(spawns=(LEFT, OFF_LINE))
    run(game, 1, bolt_at(1100, 400))
    game.state.interrupt(0)
    run(game, 10)
    me = game.state.champions[0]
    assert game.state.projectiles == [] and me.cast is None
    assert me.cooldowns["bolt"] > 0


def test_pull_moves_target_and_blocks_its_casts():
    game = make_game()
    enemy = game.state.champions[1]
    game.state.force_move(1, -1.0, 0.0, 50.0, 300.0)  # yank 300 units left over 6 ticks
    run(game, 1, a1=bolt_at(960, 400))
    assert enemy.cast is None
    assert game.observe(1).me.forced
    run(game, 5)
    assert enemy.x == pytest.approx(660.0) and enemy.forced is None


def test_capsule_entry():
    # Wall from (0,-50) to (0,50); circle radius 10 moving along +x from x=-100.
    assert segment_capsule_entry(-100, 0, 100, 0, 0, -50, 0, 50, 10) == pytest.approx(0.45)
    assert segment_capsule_entry(-100, 0, -50, 0, 0, -50, 0, 50, 10) == -1.0
    assert segment_capsule_entry(-100, 55, 100, 55, 0, -50, 0, 50, 10) == pytest.approx(
        (100 - math.sqrt(100 - 25)) / 200)  # clips the rounded end
    assert segment_capsule_entry(-5, 0, 100, 0, 0, -50, 0, 50, 10) == 0.0
    assert segment_capsule_entry(-100, 70, 100, 70, 0, -50, 0, 50, 10) == -1.0


def test_box_exit():
    assert segment_box_exit(10, 10, 20, 20, 100, 100) == -1.0
    assert segment_box_exit(90, 50, 110, 50, 100, 100) == pytest.approx(0.5)
    assert segment_box_exit(50, 10, 50, -30, 100, 100) == pytest.approx(0.25)
