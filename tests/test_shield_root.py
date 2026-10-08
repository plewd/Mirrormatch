import pytest

from arena.bots import make_bot
from arena.bots.common import predict_intercept
from arena.config import DEFAULT_CONFIG
from arena.sim import Action, Cast, Vec2
from arena.sim.types import ChampionView, Observation, ProjectileView
from conftest import LEFT, RIGHT, bolt_at, make_game, move, run


def use(aid, x, y):
    return Action(cast=Cast(aid, Vec2(x, y)))


def quiet_game(spawns=(LEFT, RIGHT)):
    game = make_game(spawns=spawns)
    game.state.next_pickup_tick = 10**9
    return game


def test_shield_is_instant_self_cast_and_expires():
    game = quiet_game()
    me = game.state.champions[0]
    me.item = "shield"
    run(game, 1, use("shield", *LEFT))  # aim on self is fine: untargeted
    assert me.item is None and me.cast is None
    assert game.observe(0).me.shielded == pytest.approx((45 - 1) / 30)
    run(game, 44)
    assert me.shield_ticks == 0


def test_shield_blocks_root_shot():
    game = quiet_game()
    game.state.champions[1].item = "shield"
    game.state.champions[0].item = "root"
    run(game, 1, use("root", 960, 400))
    enemy_x = game.state.champions[1].x
    while not game.state.projectiles or game.state.projectiles[0].x < enemy_x - 300:
        run(game, 1)
    run(game, 1, a1=use("shield", 0, 0))  # raise it just before impact (the wave is slower than the shield lasts)
    while game.state.projectiles:
        run(game, 1)
    enemy = game.state.champions[1]
    assert enemy.root_ticks == 0 and enemy.shield_ticks == 0 and game.state.projectiles == []


def test_root_shot_roots_without_damage():
    game = quiet_game()
    game.state.champions[0].item = "root"
    run(game, 1, use("root", 960, 400))
    for _ in range(80):
        run(game, 1)
        if game.state.champions[1].root_ticks:
            break
    enemy = game.state.champions[1]
    assert enemy.hp == 3 and enemy.root_ticks == game.params.abilities["root"].duration_ticks


def test_root_then_bolt_lands_on_a_fleeing_target():
    """The combo: a led root shot, then a Bolt at the rooted (now stationary) target."""
    game = quiet_game(spawns=((400.0, 400.0), (800.0, 400.0)))
    game.state.champions[0].item = "root"
    flee = move(800, 50)  # player 1 runs perpendicular to the shots
    run(game, 1, a1=flee)  # get moving so the lead has a velocity to work with
    run(game, 1, Action(cast=Cast("root", predict_intercept(game.observe(0), DEFAULT_CONFIG, "root"))), flee)
    for _ in range(40):
        if game.state.champions[1].root_ticks:
            break
        run(game, 1, a1=flee)
    enemy = game.state.champions[1]
    assert enemy.root_ticks > 0
    run(game, 1, bolt_at(enemy.x, enemy.y), flee)
    run(game, 20, a1=flee)
    assert enemy.hp == 2


def test_dodger_shields_when_rooted_and_threatened():
    bot = make_bot("dodger")
    me = ChampionView(Vec2(300, 400), Vec2(0, 0), 3, {"bolt": 0.0, "dash": 0.0}, None, 0.0, rooted=0.5, item="shield")
    enemy = ChampionView(Vec2(900, 400), Vec2(0, 0), 3, {"bolt": 0.0, "dash": 0.0}, None, 0.0)
    bolt = ProjectileView(Vec2(500, 400), Vec2(-1200, 0), is_own=False, ability_id="bolt")
    a = bot.act(Observation(me, enemy, (bolt,), 60.0))
    assert a.cast is not None and a.cast.ability_id == "shield"


def test_leader_shields_just_before_impact():
    bot = make_bot("leader")
    me = ChampionView(Vec2(300, 400), Vec2(0, 0), 3, {"bolt": 1.0, "dash": 0.0}, None, 0.0, item="shield")
    enemy = ChampionView(Vec2(900, 400), Vec2(0, 0), 3, {"bolt": 0.0, "dash": 0.0}, None, 0.0)
    far = ProjectileView(Vec2(900, 400), Vec2(-1200, 0), is_own=False, ability_id="bolt")
    near = ProjectileView(Vec2(500, 400), Vec2(-1200, 0), is_own=False, ability_id="bolt")
    assert bot.act(Observation(me, enemy, (far,), 60.0)).cast is None
    assert bot.act(Observation(me, enemy, (near,), 60.0)).cast.ability_id == "shield"


def test_config_has_every_pool_ability():
    for aid in DEFAULT_CONFIG.pickup_pool:
        assert aid in DEFAULT_CONFIG.abilities


def test_root_blocks_exactly_its_duration_in_movement_steps():
    game = quiet_game()
    enemy = game.state.champions[1]
    game.state.champions[0].item = "root"
    run(game, 1, use("root", 960, 400))
    while not enemy.root_ticks:
        run(game, 1)
    frozen = 0
    while True:
        x0 = enemy.x
        run(game, 1, a1=move(900, 100))
        if enemy.x != x0:
            break
        frozen += 1
    assert frozen == game.params.abilities["root"].duration_ticks


def bolt_into_shield(hp: int):
    """Player 0 bolts a standing, shielded player 1 at `hp` HP; returns the game after impact."""
    game = quiet_game()
    enemy = game.state.champions[1]
    enemy.hp, enemy.item = hp, "shield"
    run(game, 1, bolt_at(*RIGHT), use("shield", 0, 0))
    events = []
    for _ in range(60):
        run(game, 1)
        events += game.state.events
        if any(ev[0] in ("blocked", "hit") for ev in events):
            break
    return game, events


def test_a_successful_block_heals_one_hp():
    game, events = bolt_into_shield(hp=2)
    enemy = game.state.champions[1]
    assert enemy.hp == 3 and enemy.shield_ticks == 0
    assert ("blocked", 1, 0, "bolt") in events and ("heal", 1, 1) in events


def test_a_block_at_full_hp_heals_nothing():
    game, events = bolt_into_shield(hp=3)
    assert game.state.champions[1].hp == 3
    assert ("blocked", 1, 0, "bolt") in events and not any(ev[0] == "heal" for ev in events)


def test_blocking_a_blast_heals_too():
    from arena.sim.state import Zone

    game = quiet_game()
    enemy = game.state.champions[1]
    enemy.hp, enemy.item = 1, "shield"
    run(game, 1, a1=use("shield", 0, 0))
    game.state.zones.append(Zone("blast", 0, enemy.x, enemy.y, 110, 1, 0))
    run(game, 1)
    assert enemy.hp == 2 and not game.state.done
    assert ("blocked", 1, 0, "blast") in game.state.events and ("heal", 1, 1) in game.state.events
