import numpy as np
import pytest

from arena.sim import Action, Cast, Vec2
from arena.sim.state import Pickup
from conftest import LEFT, RIGHT, make_game, move, run


def use(aid, x, y):
    return Action(cast=Cast(aid, Vec2(x, y)))


def quiet_game(spawns=(LEFT, RIGHT)):
    """A game whose pickup schedule won't fire during the test."""
    game = make_game(spawns=spawns)
    game.state.next_pickup_tick = 10**9
    return game


def spawn_one(game, c0, c1):
    """Put the champions at c0/c1, force a pickup spawn this tick, and return the new pickup."""
    s = game.state
    (s.champions[0].x, s.champions[0].y), (s.champions[1].x, s.champions[1].y) = c0, c1
    before = list(s.pickups)
    s.next_pickup_tick = s.tick
    game._update_pickups()
    (new,) = [pk for pk in s.pickups if pk not in before]
    return new


def test_pickups_spawn_one_at_a_time_and_at_most_two_on_the_map():
    game = make_game(spawns=((40.0, 40.0), (1160.0, 760.0)))  # corners: far from every spawn spot
    p = game.params
    run(game, p.pickup_first_tick)
    assert game.state.pickups == []
    run(game, 1)
    assert len(game.state.pickups) == 1
    run(game, p.pickup_interval_ticks)
    a, b = game.state.pickups
    assert a.ability_id != b.ability_id  # never two of the same on the map
    run(game, 2 * p.pickup_interval_ticks)  # the map is full: no third
    assert len(game.state.pickups) == 2


def test_every_spawn_is_equidistant_from_both_players_and_fair_to_reach():
    rng = np.random.default_rng(7)
    for seed in range(300):
        game = make_game(seed=seed)
        p = game.params
        margin = p.champion_radius + p.pickup_radius
        hx, hy = game.heal_spot()
        r = p.champion_radius
        c0 = (rng.uniform(r, p.width - r), rng.uniform(r, p.height - r))
        c1 = (rng.uniform(r, p.width - r), rng.uniform(r, p.height - r))
        for _ in range(2):
            pk = spawn_one(game, c0, c1)
            d0, d1 = np.hypot(pk.x - c0[0], pk.y - c0[1]), np.hypot(pk.x - c1[0], pk.y - c1[1])
            assert d0 == pytest.approx(d1, abs=1e-6)
            assert margin <= pk.x <= p.width - margin and margin <= pk.y <= p.height - margin
            assert np.hypot(pk.x - hx, pk.y - hy) >= p.heal_radius + p.pickup_radius
            if np.hypot(c0[0] - c1[0], c0[1] - c1[1]) > 100:  # room on the line to keep away from both
                assert d0 >= p.pickup_min_distance - 1e-6
        a, b = game.state.pickups
        assert a.ability_id != b.ability_id


def test_stacked_champions_still_get_a_pickup_in_the_arena():
    game = make_game()
    pk = spawn_one(game, (600.0, 200.0), (600.0, 200.0))
    p = game.params
    assert 0 < pk.x < p.width and 0 < pk.y < p.height
    assert np.hypot(pk.x - 600.0, pk.y - 200.0) >= p.pickup_min_distance - 1e-6


def test_walking_over_a_pickup_collects_it_only_with_an_empty_slot():
    game = quiet_game()
    game.state.pickups = [Pickup(400.0, 400.0, "boomerang"), Pickup(500.0, 400.0, "boomerang")]
    run(game, 40, move(600, 400))
    me = game.state.champions[0]
    assert me.item == "boomerang"
    assert len(game.state.pickups) == 1  # the second one was left: slot full
    assert game.observe(0).me.item == "boomerang" and game.observe(1).enemy.item == "boomerang"


def test_touching_on_the_same_tick_gives_both_players_the_ability():
    game = quiet_game(spawns=((580.0, 400.0), (630.0, 400.0)))
    game.state.pickups = [Pickup(600.0, 400.0, "boomerang")]
    run(game, 1)
    assert [c.item for c in game.state.champions] == ["boomerang", "boomerang"]
    assert game.state.pickups == []


def test_same_tick_contest_with_one_full_slot_goes_to_the_other():
    game = quiet_game(spawns=((580.0, 400.0), (630.0, 400.0)))
    game.state.champions[0].item = "shield"
    game.state.pickups = [Pickup(600.0, 400.0, "boomerang")]
    run(game, 1)
    assert [c.item for c in game.state.champions] == ["shield", "boomerang"]


def test_item_is_used_once_and_only_when_held():
    game = quiet_game(spawns=(LEFT, (960.0, 100.0)))
    me = game.state.champions[0]
    run(game, 1, use("boomerang", 1000, 400))  # not held: ignored
    assert me.cast is None
    me.item = "boomerang"
    run(game, 1, use("boomerang", 1000, 400))
    assert me.cast is not None and me.item is None
    run(game, 10)
    assert len(game.state.projectiles) == 1


def test_interrupted_item_cast_is_lost():
    game = quiet_game()
    game.state.champions[0].item = "boomerang"
    run(game, 1, use("boomerang", 960, 400))
    game.state.interrupt(0)
    run(game, 30)
    assert game.state.projectiles == [] and game.state.champions[0].item is None


def test_boomerang_hits_on_the_way_out_and_back_then_is_caught():
    game = quiet_game(spawns=((300.0, 400.0), (700.0, 400.0)))
    game.state.champions[0].item = "boomerang"
    run(game, 1, use("boomerang", 1000, 400))
    hits = []
    for _ in range(90):
        before = game.state.champions[1].hp
        run(game, 1)
        if game.state.champions[1].hp < before:
            hits.append(game.state.tick)
        if not game.state.projectiles and hits:
            break
    assert len(hits) == 2 and hits[1] - hits[0] > 10
    assert game.state.projectiles == []  # caught by the caster


def test_boomerang_turns_at_the_arena_edge():
    game = quiet_game(spawns=((1000.0, 400.0), (200.0, 100.0)))
    game.state.champions[0].item = "boomerang"
    run(game, 1, use("boomerang", 1190, 400))
    run(game, 12)  # 6 ticks cast + ~7 out would pass x=1200 if it didn't turn
    (proj,) = game.state.projectiles
    assert proj.phase == 1 and proj.x <= 1200


def test_pickups_are_mirrored_in_observations():
    game = quiet_game()
    game.state.pickups = [Pickup(300.0, 200.0, "boomerang")]
    assert game.observe(0).pickups[0].pos == Vec2(300.0, 200.0)
    assert game.observe(1).pickups[0].pos == Vec2(900.0, 200.0)


def throw_boomerang(x, y, ax, ay):
    """Returns the boomerang's phase when it disappears (1 = it came back)."""
    enemy_at = (1150.0, 50.0) if x < 600 else (50.0, 750.0)
    game = quiet_game(spawns=((x, y), enemy_at))
    game.state.champions[0].item = "boomerang"
    run(game, 1, use("boomerang", ax, ay))
    phase = None
    for _ in range(150):
        run(game, 1)
        if game.state.projectiles:
            phase = game.state.projectiles[0].phase
        elif phase is not None:
            return phase
    return phase


def test_boomerang_turning_at_max_range_on_the_edge_still_returns():
    # Review finding: max range and the arena edge on the same tick destroyed it.
    assert throw_boomerang(590.0, 400.0, 0.0, 400.0) == 1


def test_boomerang_never_dies_outbound_at_the_edge():
    rng = np.random.default_rng(0)
    for _ in range(150):
        x, y = float(rng.uniform(40, 1160)), float(rng.uniform(40, 760))
        ang = rng.uniform(0, 2 * np.pi)
        assert throw_boomerang(x, y, x + 500 * np.cos(ang), y + 500 * np.sin(ang)) == 1, (x, y, ang)
