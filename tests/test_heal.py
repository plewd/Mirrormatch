import pytest

from arena.sim.types import Vec2
from conftest import config_with, make_game, move, run

CENTER = (600.0, 400.0)


def quiet(spawns=((240.0, 400.0), (960.0, 400.0)), config=None):
    game = make_game(spawns=spawns, config=config) if config else make_game(spawns=spawns)
    game.state.next_pickup_tick = 10**9
    return game


def test_orb_appears_on_schedule_and_is_public():
    game = quiet()
    p = game.params
    obs = game.observe(0)
    assert obs.heal is None and obs.heal_in == pytest.approx(15.0)
    run(game, p.heal_first_tick)
    assert not game.state.heal_up and game.observe(0).heal_in == 0.0  # appears during the next step
    run(game, 1)
    assert game.state.heal_up
    assert game.observe(0).heal == Vec2(*CENTER) == game.observe(1).heal  # center: same in both frames
    assert game.observe(0).heal_in == 0.0


def test_heals_one_hp_capped_and_respawns_after_being_taken():
    game = quiet(spawns=(CENTER, (960.0, 100.0)))
    me = game.state.champions[0]
    me.hp = 1
    run(game, game.params.heal_first_tick + 1)
    assert me.hp == 2 and not game.state.heal_up
    assert game.observe(0).heal_in == pytest.approx(15.0 - 1 / 30, abs=0.05)
    run(game, game.params.heal_respawn_ticks)
    assert me.hp == 3
    run(game, game.params.heal_respawn_ticks + 1)
    assert me.hp == 3  # capped; taking it at full HP still uses it up (denial)
    assert not game.state.heal_up


def test_both_heal_if_they_touch_it_on_the_same_tick():
    game = quiet(spawns=((580.0, 400.0), (620.0, 400.0)))
    for c in game.state.champions:
        c.hp = 1
    run(game, game.params.heal_first_tick + 1)
    assert [c.hp for c in game.state.champions] == [2, 2]


def test_walking_in_takes_it():
    game = quiet()
    game.state.champions[0].hp = 2
    run(game, game.params.heal_first_tick)
    run(game, 60, move(*CENTER))
    assert game.state.champions[0].hp == 3 and not game.state.heal_up


def test_heal_can_swing_a_timeout():
    game = quiet(spawns=(CENTER, (960.0, 100.0)), config=config_with(time_limit=16.0))
    game.state.next_pickup_tick = 10**9
    a, b = game.state.champions
    a.hp, b.hp = 2, 2
    while not game.state.done:
        run(game, 1)
    assert game.state.winner == 0 and (a.hp, b.hp) == (3, 2)


def test_heal_sensors_and_go_to_heal_in_rules():
    from arena.bots.rules import RuleBot

    b = RuleBot({"name": "t", "rules": [
        {"if": [{"sensor": "heal_up"}, {"sensor": "closer_to_heal"}], "then": {"action": "go_to_heal"}},
        {"if": [{"sensor": "heal_in", "op": "<", "value": 2}], "then": {"action": "go_to_heal"}},
        {"if": [], "then": {"action": "retreat"}},
    ]})
    game = quiet(spawns=((500.0, 400.0), (900.0, 400.0)))
    assert b.act(game.observe(0)).move != Vec2(*CENTER)  # 15 s away: retreat
    run(game, game.params.heal_first_tick - 30)  # 1 s before it appears
    assert b.act(game.observe(0)).move == Vec2(*CENTER)
    run(game, 31)
    assert game.state.heal_up and b.act(game.observe(0)).move == Vec2(*CENTER)


def test_leader_contests_the_heal():
    from arena.bots import make_bot

    game = quiet()
    leader = make_bot("leader")
    run(game, game.params.heal_first_tick + 1)
    assert leader.act(game.observe(0)).move == Vec2(*CENTER)
    # In a long game (high HP, so nobody dies first) the leader walks in and takes it.
    import numpy as np

    g = make_game(config=config_with(champion_hp=50))
    a, b = make_bot("leader"), make_bot("idle")
    a.reset(np.random.default_rng(0))
    b.reset(np.random.default_rng(1))
    took = False
    while g.state.tick <= g.params.heal_first_tick + 150:
        g.step(a.act(g.observe(0)), b.act(g.observe(1)))
        took = took or any(ev[0] == "heal" and ev[1] == 0 for ev in g.state.events)  # the orb, at full HP: +0
    assert took and not g.state.heal_up
