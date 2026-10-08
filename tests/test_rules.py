import json
import pathlib

import numpy as np
import pytest

from arena.bots import make_bot
from arena.bots.rules import ACTIONS, SENSORS, RuleBot, RuleError, main, validate, vocabulary
from arena.match import run_match
from arena.sim.types import ChampionView, Observation, PickupView, ProjectileView, Vec2

BOTS_DIR = pathlib.Path(__file__).parent.parent / "bots"


def view(x, y, bolt_cd=0.0, dash_cd=0.0, item=None, rooted=0.0) -> ChampionView:
    return ChampionView(Vec2(x, y), Vec2(0, 0), 3, {"bolt": bolt_cd, "dash": dash_cd}, None, 0.0, rooted=rooted, item=item)


def obs(me, enemy, projectiles=(), pickups=()) -> Observation:
    return Observation(me, enemy, tuple(projectiles), 60.0, pickups=tuple(pickups))


def bot(*rules) -> RuleBot:
    return RuleBot({"name": "t", "version": 1, "rules": list(rules)})


def rule(action, *conds, **params):
    return {"if": list(conds), "then": {"action": action, **params}}


@pytest.mark.parametrize("path", sorted(BOTS_DIR.glob("*.json")), ids=lambda p: p.name)
def test_starter_bots_are_valid_and_play(path):
    assert validate(json.loads(path.read_text())) == []
    assert run_match(make_bot(str(path)), make_bot("aimer"), seed=0).ticks > 0


@pytest.mark.parametrize("spec, fragment", [
    ({"rules": "nope"}, "'rules' must be a list"),
    ({"rules": [rule("teleport")]}, "unknown action 'teleport'"),
    ({"rules": [rule("shoot")]}, "missing 'aim'"),
    ({"rules": [rule("shoot", aim="sideways")]}, "'aim' must be one of lead, direct"),
    ({"rules": [rule("hold", {"sensor": "x_ray"})]}, "unknown sensor 'x_ray'"),
    ({"rules": [rule("hold", {"sensor": "enemy_distance", "value": 3})]}, "needs 'op'"),
    ({"rules": [rule("hold", {"sensor": "enemy_distance", "op": "<", "value": True})]}, "numeric 'value'"),
    ({"rules": [rule("hold", {"sensor": "ready"})]}, "missing 'ability'"),
    ({"rules": [rule("hold", {"sensor": "holding", "item": "sword"})]}, "'item' must be one of"),
    ({"rules": [rule("hold", {"not": {"sensor": "threatened"}, "x": 1})]}, "'not' can't have other keys"),
    ({"rules": [rule("hold")] * 65}, "too many rules"),
    ({"version": 2, "rules": []}, "unsupported version"),
])
def test_validation_messages(spec, fragment):
    errors = validate(spec)
    assert any(fragment in e for e in errors), errors
    with pytest.raises(RuleError):
        RuleBot(spec)


def test_first_match_per_channel_lets_it_walk_and_shoot():
    b = bot(rule("shoot", aim="direct"), rule("approach"), rule("retreat"))
    a = b.act(obs(view(300, 400), view(800, 400)))
    assert a.cast.ability_id == "bolt" and a.cast.aim == Vec2(800, 400)
    assert a.move == Vec2(800, 400)  # approach, not retreat


def test_actions_that_cant_happen_fall_through():
    b = bot(rule("shoot", aim="direct"), rule("use_item", aim="direct"))
    a = b.act(obs(view(300, 400, bolt_cd=1.0, item="hook"), view(800, 400)))
    assert a.cast.ability_id == "hook"
    assert b.act(obs(view(300, 400, bolt_cd=1.0), view(800, 400))).cast is None  # nothing left to try


def test_hold_fire_blocks_lower_ability_rules():
    b = bot(rule("hold_fire", {"sensor": "enemy_distance", "op": "<", "value": 600}), rule("shoot", aim="lead"))
    assert b.act(obs(view(300, 400), view(800, 400))).cast is None
    assert b.act(obs(view(100, 400), view(800, 400))).cast is not None


def test_hold_stops_once():
    b = bot(rule("hold"))
    assert b.act(obs(view(300, 400), view(800, 400))).move == Vec2(300, 400)
    assert b.act(obs(view(310, 400), view(800, 400))).move is None  # already holding: don't drag back


def test_not_and_number_conditions():
    b = bot(rule("retreat", {"not": {"sensor": "enemy_distance", "op": ">", "value": 300}}), rule("approach"))
    assert b.act(obs(view(500, 400), view(700, 400))).move.x < 500  # 200 away: retreat
    assert b.act(obs(view(100, 400), view(700, 400))).move == Vec2(700, 400)


def test_threat_sensors_and_dash_away():
    b = bot(rule("dash", {"sensor": "threatened"}, {"not": {"sensor": "can_sidestep"}}, direction="away_from_threat"),
            rule("hold_fire", {"sensor": "threatened"}), rule("shoot", aim="lead"))
    close = ProjectileView(Vec2(420, 400), Vec2(-1200, 0), is_own=False, ability_id="bolt")
    a = b.act(obs(view(300, 400), view(900, 400), [close]))
    assert a.cast.ability_id == "dash"
    a = b.act(obs(view(300, 400, dash_cd=3.0), view(900, 400), [close]))
    assert a.cast is None  # dash unavailable falls through to hold_fire


def test_go_to_pickup_and_closer_to_pickup():
    b = bot(rule("go_to_pickup", {"sensor": "closer_to_pickup"}), rule("hold"))
    pk = PickupView(Vec2(400, 300), "wall")
    assert b.act(obs(view(300, 400), view(900, 400), pickups=[pk])).move == pk.pos
    far = PickupView(Vec2(850, 400), "wall")
    assert b.act(obs(view(300, 400), view(900, 400), pickups=[far])).move != far.pos


def test_in_range_is_false_for_shield_and_wall():
    b = bot(rule("use_item", {"sensor": "in_range", "ability": "item"}, aim="lead"))
    assert b.act(obs(view(300, 400, item="shield"), view(500, 400))).cast is None
    assert b.act(obs(view(300, 400, item="hook"), view(500, 400))).cast.ability_id == "hook"


def test_wander_is_seeded():
    def moves(seed):
        b = bot(rule("wander"))
        b.reset(np.random.default_rng(seed))
        return [b.act(obs(view(300, 400), view(900, 400))).move for _ in range(50)]
    assert moves(1) == moves(1) and moves(1) != moves(2)


def test_vocabulary_covers_everything_and_is_json():
    vocab = json.loads(json.dumps(vocabulary()))
    assert set(vocab["sensors"]) == set(SENSORS) and set(vocab["actions"]) == set(ACTIONS)
    assert vocab["actions"]["dash"]["params"]["direction"][0] == "away_from_threat"
    assert "hook" in vocab["sensors"]["holding"]["params"]["item"]


def test_check_cli(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"rules": [{"then": {"action": "fly"}}]}')
    with pytest.raises(SystemExit) as exit_info:
        main(["check", str(BOTS_DIR / "leader.json"), str(bad)])
    out = capsys.readouterr().out
    assert exit_info.value.code == 1 and "ok      " in out and "unknown action 'fly'" in out


# ---- reading the enemy, memory, modes, chance --------------------------------------

def cview(x, y, bolt_cd=0.0, dash_cd=0.0, hp=3, item=None) -> ChampionView:
    return ChampionView(Vec2(x, y), Vec2(0, 0), hp, {"bolt": bolt_cd, "dash": dash_cd}, None, 0.0, item=item)


def at(time_left, me, enemy):
    return Observation(me, enemy, (), time_left)


def probe(*conds):
    """A bot that strafes iff all conditions hold (it holds otherwise)."""
    return bot(rule("strafe", *conds), rule("hold"))


def fired(b, o) -> bool:
    return b.act(o).move not in (None, o.me.pos)


def test_enemy_ready_and_cooldown():
    b = probe({"sensor": "enemy_ready", "ability": "dash"})
    assert fired(b, at(60, cview(300, 400), cview(800, 400)))
    b = probe({"sensor": "enemy_ready", "ability": "dash"})
    assert not fired(b, at(60, cview(300, 400), cview(800, 400, dash_cd=2.0)))
    b = probe({"sensor": "enemy_cooldown", "ability": "dash", "op": ">", "value": 1.5})
    assert fired(b, at(60, cview(300, 400), cview(800, 400, dash_cd=2.0)))


def test_since_enemy_used_is_backdated_from_the_cooldown():
    dash_cd = 5.0  # config
    b = probe({"sensor": "since_enemy_used", "ability": "dash", "op": "<", "value": 1.0})
    assert not fired(b, at(60.0, cview(300, 400), cview(800, 400)))  # never dashed: 99
    # First seen 0.4 s into the cooldown (as with a reaction delay): it dashed 0.4 s ago.
    assert fired(b, at(59.0, cview(300, 400), cview(800, 400, dash_cd=dash_cd - 0.4)))
    assert b.memory.since(b.memory.used["enemy"]["dash"], 59.0) == pytest.approx(0.4)
    assert not fired(b, at(58.0, cview(300, 400), cview(800, 400, dash_cd=dash_cd - 1.4)))  # 1.4 s ago now


def test_hit_timers_and_item_use():
    b = probe({"sensor": "since_i_was_hit", "op": "<", "value": 1.0})
    assert not fired(b, at(60.0, cview(300, 400), cview(800, 400)))
    assert fired(b, at(59.5, cview(300, 400, hp=2), cview(800, 400)))
    assert not fired(b, at(58.0, cview(300, 400, hp=2), cview(800, 400)))
    b = probe({"sensor": "since_enemy_used", "ability": "item", "op": "<", "value": 1.0})
    assert not fired(b, at(60.0, cview(300, 400), cview(800, 400, item="hook")))
    assert fired(b, at(59.0, cview(300, 400), cview(800, 400)))  # the hook is gone: used it


def test_set_mode_applies_immediately_and_only_once_per_decision():
    b = bot(rule("set_mode", mode="aggressive"),
            rule("set_mode", mode="defensive"),  # second set_mode in the same decision: skipped
            rule("approach", {"sensor": "in_mode", "mode": "aggressive"}),
            rule("retreat"))
    o = at(60.0, cview(300, 400), cview(800, 400))
    assert b.act(o).move == Vec2(800, 400)
    assert b.memory.mode == "aggressive"


def test_time_in_mode_and_mode_switching_cycle():
    b = bot(rule("set_mode", {"sensor": "in_mode", "mode": "normal"}, {"sensor": "time_in_mode", "op": ">", "value": 2.0},
                 mode="baiting"),
            rule("set_mode", {"sensor": "in_mode", "mode": "baiting"}, {"sensor": "time_in_mode", "op": ">", "value": 1.0},
                 mode="normal"),
            rule("hold"))
    modes = []
    for k in range(80):  # 0.1 s steps
        b.act(at(60.0 - k * 0.1, cview(300, 400), cview(800, 400)))
        modes.append(b.memory.mode)
    switches = [i for i in range(1, len(modes)) if modes[i] != modes[i - 1]]
    assert modes[0] == "normal" and len(switches) >= 4
    assert switches[1] - switches[0] == pytest.approx(11, abs=1)  # ~1 s in baiting before switching back


def test_chance_is_seeded_and_bounded():
    def rate(pct, seed):
        b = probe({"sensor": "chance", "value": pct})
        b.reset(np.random.default_rng(seed))
        o = at(60.0, cview(300, 400), cview(800, 400))
        hits = 0
        for _ in range(400):
            b.holding_still = False
            hits += fired(b, o)
        return hits
    assert rate(0, 1) == 0 and rate(100, 1) == 400
    assert 150 < rate(50, 1) < 250 and rate(50, 1) == rate(50, 1) and rate(50, 1) != rate(50, 2)


@pytest.mark.parametrize("spec, fragment", [
    ({"rules": [rule("hold", {"sensor": "chance", "value": 140})]}, "from 0 to 100"),
    ({"rules": [rule("hold", {"sensor": "chance"})]}, "from 0 to 100"),
    ({"rules": [rule("set_mode", mode="sleepy")]}, "'mode' must be one of"),
    ({"rules": [rule("hold", {"sensor": "enemy_cooldown", "ability": "item", "op": ">", "value": 1})]}, "'ability' must be one of"),
])
def test_new_validation_messages(spec, fragment):
    assert any(fragment in e for e in validate(spec)), validate(spec)


def test_strafe_with_champions_on_the_same_spot_does_not_crash():
    # Found by eval: both bots walked onto the center heal and strafe divided by zero.
    b = bot(rule("strafe"))
    a = b.act(obs(view(600, 400), view(600, 400)))
    assert a.move is not None and a.move != Vec2(600, 400)


def test_trace_records_what_each_rule_did():
    b = bot(
        rule("shoot", {"sensor": "enemy_distance", "op": "<", "value": 100}, aim="lead"),  # false: 500 away
        rule("shoot", aim="lead"),                     # couldn't: Bolt on cooldown
        rule("approach"),                               # fired (move)
        rule("retreat"),                                # skipped: move already done
        rule("hold_fire"),                              # fired (ability)
        rule("set_mode", mode="aggressive"),            # fired (mode): all channels done now
        rule("wander"),                                 # unreached
    )
    b.act(obs(view(300, 400, bolt_cd=1.0), view(800, 400)))
    assert b.trace["status"] == ["false", "couldnt", "fired", "skipped", "fired", "fired", "unreached"]
    assert b.trace["fired"] == {"move": 2, "ability": 4, "mode": 5}
    assert b.trace["mode"] == "aggressive"


def test_session_snapshot_carries_decision_traces():
    from arena.webapi import HUMAN, Session

    spec = json.loads((BOTS_DIR / "leader.json").read_text())
    s = Session(json.dumps(spec), "dodger", seed=1)
    snap = json.loads(s.advance(10))
    left, right = snap["debug"]
    assert left["kind"] == "rules" and "move" in left["fired"] and len(left["status"]) == len(spec["rules"])
    assert right["kind"] == "other"
    human = json.loads(Session(HUMAN, "bots/leader.json", seed=1).advance(3))["debug"]
    assert human[0] is None and human[1]["kind"] == "rules"
