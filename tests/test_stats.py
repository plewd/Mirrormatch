import json

from arena.sim import Action, Cast, Vec2
from arena.sim.state import Pickup, Zone
from arena.webapi import Session, new_stats, tally
from conftest import bolt_at, make_game, run


def quiet(spawns=((240.0, 400.0), (960.0, 400.0))):
    game = make_game(spawns=spawns)
    game.state.next_pickup_tick = game.state.next_heal_tick = 10**9
    return game


def play(game, ticks, *actions):
    stats = [new_stats(), new_stats()]
    events = []
    for k in range(ticks):
        game.step(*(actions if k == 0 else (Action(), Action())))
        events += game.state.events
        tally(stats, game)
    return stats, events


def test_bolt_cast_hit_and_damage_are_attributed():
    game = quiet()
    stats, events = play(game, 40, bolt_at(960, 400), Action())
    kinds = [e[0] for e in events]
    assert kinds == ["cast", "hit", "damage"]
    assert events[2] == ("damage", 0, 1, "bolt", 1)
    assert stats[0]["casts"] == {"bolt": 1} and stats[0]["hits"] == {"bolt": 1} and stats[0]["dealt"] == {"bolt": 1}
    assert stats[1]["taken"] == {"bolt": 1}


def test_zone_damage_is_attributed_to_its_ability_and_owner():
    game = quiet()
    game.state.zones.append(Zone("blast", 0, 960.0, 400.0, 110.0, 1, 3))
    stats, events = play(game, 6, Action(), Action())
    assert ("damage", 0, 1, "blast", 1) in events and stats[0]["dealt"] == {"blast": 1}


def test_shield_blocks_pickups_and_heals():
    game = quiet()
    game.state.shield(1, 300)
    game.state.pickups = [Pickup(240.0, 400.0, "hook")]
    stats, events = play(game, 40, bolt_at(960, 400), Action())
    assert ("blocked", 1, 0, "bolt") in events and stats[1]["blocks"] == 1
    assert stats[0]["pickups"] == 1 and stats[1]["taken"] == {}

    game = quiet(spawns=((600.0, 400.0), (960.0, 100.0)))
    game.state.next_heal_tick = 0
    stats, events = play(game, 2, Action(), Action())
    assert ("heal", 0, 0) in events and stats[0]["heals"] == 1 and stats[0]["healed"] == 0  # full HP: denial


def test_events_reset_every_tick_and_item_use_counts():
    game = quiet()
    game.state.champions[0].item = "hook"
    game.step(Action(cast=Cast("hook", Vec2(960, 400))), Action())
    assert [e[0] for e in game.state.events] == ["cast"]
    game.step(Action(), Action())
    assert game.state.events == []


def test_session_stats_survive_seeking():
    a = Session("bots/baiter.json", "dodger", seed=8)
    a.advance(10**9)
    b = Session("bots/baiter.json", "dodger", seed=8)
    length = b.prepare_timeline()
    b.seek(length // 2)
    b.seek(5)
    b.seek(length)
    assert json.loads(b.snapshot())["stats"] == json.loads(a.snapshot())["stats"]
    st = json.loads(a.snapshot())["stats"]
    assert st[0]["casts"].get("bolt", 0) >= st[0]["hits"].get("bolt", 0)
    assert sum(st[1]["taken"].values()) == 3 - a.game.state.champions[1].hp + st[1]["healed"]
