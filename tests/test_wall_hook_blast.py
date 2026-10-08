import math

import pytest

from arena.sim import Action, Cast, Vec2
from arena.sim.state import Wall, Zone
from conftest import LEFT, RIGHT, bolt_at, make_game, move, run  # noqa: F401


def use(aid, x, y):
    return Action(cast=Cast(aid, Vec2(x, y)))


def quiet_game(spawns=(LEFT, RIGHT)):
    game = make_game(spawns=spawns)
    game.state.next_pickup_tick = 10**9
    return game


# ---- wall ------------------------------------------------------------------

def test_wall_is_placed_perpendicular_at_aim_point_clamped_to_range():
    game = quiet_game()
    me = game.state.champions[0]
    me.item = "wall"
    run(game, 1, use("wall", 1100, 400))  # 860 away; max placement 450
    run(game, 3)
    (wall,) = game.state.walls
    assert (wall.ax + wall.bx) / 2 == pytest.approx(LEFT[0] + 450)
    assert wall.ax == pytest.approx(wall.bx)  # vertical, i.e. perpendicular to a horizontal aim
    assert abs(wall.ay - wall.by) == pytest.approx(160)
    run(game, game.params.abilities["wall"].duration_ticks)
    assert game.state.walls == []


@pytest.mark.parametrize("shooter", [0, 1])
def test_wall_blocks_projectiles_from_both_sides(shooter):
    game = quiet_game()
    game.state.walls.append(Wall(600, 300, 600, 500, 0, 300))
    shot = bolt_at(960, 400)
    run(game, 1, *((shot,) if shooter == 0 else (Action(), shot)))
    run(game, 40)
    assert [c.hp for c in game.state.champions] == [3, 3]
    assert game.state.projectiles == []


def test_standing_in_a_wall_gives_no_protection():
    game = quiet_game(spawns=(LEFT, (600.0, 400.0)))
    game.state.walls.append(Wall(600, 300, 600, 500, 1, 300))  # enemy straddles its own wall
    run(game, 1, bolt_at(600, 400))
    run(game, 30)
    assert game.state.champions[1].hp == 2


def test_wall_destroys_boomerang():
    game = quiet_game()
    game.state.walls.append(Wall(600, 300, 600, 500, 1, 300))
    game.state.champions[0].item = "boomerang"
    run(game, 1, use("boomerang", 960, 400))
    run(game, 40)
    assert game.state.projectiles == [] and game.state.champions[1].hp == 3


# ---- hook ------------------------------------------------------------------

def test_hook_pulls_enemy_to_caster_and_interrupts_their_cast():
    game = quiet_game(spawns=((300.0, 400.0), (800.0, 400.0)))
    game.state.champions[0].item = "hook"
    run(game, 1, use("hook", 800, 400))  # 9-tick cast, then ~10 ticks of flight
    run(game, 13)
    enemy = game.state.champions[1]
    run(game, 1, a1=use("bolt", 900, 400))  # enemy starts an 8-tick cast the hook will cut short
    while not enemy.forced and game.state.tick < 40:
        run(game, 1)
    assert enemy.forced and enemy.cast is None and enemy.cooldowns["bolt"] > 0  # interrupted, cooldown spent
    assert all(proj.owner == 0 for proj in game.state.projectiles)  # its Bolt never fired
    run(game, 20)
    me = game.state.champions[0]
    assert math.hypot(enemy.x - me.x, enemy.y - me.y) == pytest.approx(64, abs=1)


def test_hook_on_wall_pulls_caster_to_it():
    game = quiet_game(spawns=((300.0, 400.0), (900.0, 100.0)))
    game.state.walls.append(Wall(700, 300, 700, 500, 0, 300))
    game.state.champions[0].item = "hook"
    run(game, 1, use("hook", 1000, 400))
    run(game, 30)
    me = game.state.champions[0]
    assert me.x == pytest.approx(700 - 15 - 30, abs=1)  # contact point (hook radius before the wall), minus body
    assert me.y == pytest.approx(400)


def test_hook_on_arena_edge_pulls_caster_and_stops_at_bounds():
    game = quiet_game(spawns=((300.0, 400.0), (900.0, 100.0)))
    game.state.champions[0].item = "hook"
    run(game, 1, use("hook", 300, 790))  # straight down, 400 units to the edge
    run(game, 30)
    me = game.state.champions[0]
    assert me.y == pytest.approx(770) and me.forced is None


def test_shield_blocks_hook():
    game = quiet_game(spawns=((300.0, 400.0), (800.0, 400.0)))
    game.state.champions[0].item = "hook"
    game.state.shield(1, 300)
    run(game, 1, use("hook", 800, 400))
    run(game, 30)
    enemy = game.state.champions[1]
    assert enemy.x == 800.0 and enemy.shield_ticks == 0


# ---- blast -----------------------------------------------------------------

def test_blast_roots_caster_then_telegraphs_then_damages():
    game = quiet_game(spawns=((300.0, 400.0), (800.0, 400.0)))
    p = game.params.abilities["blast"]
    me = game.state.champions[0]
    me.item = "blast"
    run(game, 1, Action(move=Vec2(300, 100), cast=Cast("blast", Vec2(800, 400))))
    run(game, p.cast_ticks - 1)
    assert (me.x, me.y) == (300.0, 400.0)  # rooted while charging
    run(game, 1)
    (zone,) = game.state.zones
    assert (zone.x, zone.y) == pytest.approx((800, 400))
    assert game.observe(1).zones[0].pos.x == pytest.approx(400)  # mirrored for player 1
    run(game, p.duration_ticks - 1)  # created on tick T, fires on tick T + duration
    assert game.state.champions[1].hp == 3 and len(game.state.zones) == 1
    run(game, 1)
    assert game.state.champions[1].hp == 2 and game.state.zones == []


def test_blast_can_be_walked_out_of_and_shielded():
    p_game = quiet_game(spawns=((300.0, 400.0), (800.0, 400.0)))
    p_game.state.champions[0].item = "blast"
    run(p_game, 1, use("blast", 800, 400), move(800, 100))
    run(p_game, 50, a1=move(800, 100))
    assert p_game.state.champions[1].hp == 3

    s_game = quiet_game(spawns=((300.0, 400.0), (800.0, 400.0)))
    s_game.state.champions[0].item = "blast"
    s_game.state.shield(1, 300)
    run(s_game, 1, use("blast", 800, 400))
    run(s_game, 50)
    assert s_game.state.champions[1].hp == 3 and s_game.state.champions[1].shield_ticks == 0


def test_hooked_enemy_is_hit_by_a_zone_it_was_pulled_into():
    """Engine interaction: a zone hits a champion who arrived by forced movement.
    (With default numbers one player can't chain their own blast into a hook:
    the 0.8 s cast + 0.6 s fuse ends before a follow-up hook lands and pulls.)"""
    game = quiet_game(spawns=((300.0, 400.0), (900.0, 400.0)))
    game.state.zones.append(Zone("blast", 0, 380.0, 400.0, 110.0, 1, 45))
    game.state.champions[0].item = "hook"
    run(game, 1, use("hook", 900, 400))
    run(game, 44)
    enemy = game.state.champions[1]
    assert enemy.x < 380 + 110 and enemy.forced is None  # arrived inside the zone before the fuse ran out
    run(game, 2)
    assert enemy.hp == 2


def test_hook_pull_on_caster_interrupts_their_cast():
    # Review finding: a caster pulled to a wall slid while still casting Bolt.
    game = quiet_game(spawns=((600.0, 400.0), (1100.0, 100.0)))
    me = game.state.champions[0]
    me.item = "hook"
    run(game, 1, use("hook", 600, 0))  # 9-tick cast, then ~8 ticks of flight to the top edge
    run(game, 12)
    run(game, 1, bolt_at(900, 400))  # an 8-tick Bolt cast the pull will cut short
    while not me.forced and game.state.tick < 40:
        run(game, 1)
    assert me.forced is not None and me.cast is None
    assert me.cooldowns["bolt"] > 0  # the Bolt was started...
    run(game, 15)
    assert not any(p.ability_id == "bolt" for p in game.state.projectiles)  # ...but never fired
