"""Goal 5: new abilities plug in without touching the sim loop.

Both abilities below are defined entirely in this file and injected through
Game(ability_types=...); in the real game they'd live in arena/sim/abilities/
and be added to ABILITY_TYPES.
"""

from dataclasses import replace

import pytest

from arena.config import BOLT, DEFAULT_CONFIG, AbilityStats
from arena.sim import Action, Cast, Game, Vec2
from arena.sim.abilities import ABILITY_TYPES
from arena.sim.abilities.base import Ability, advance_linear
from conftest import run


class Lance(Ability):
    """A slow piercing line that damages every enemy it passes through, once."""

    ability_id = "lance"

    def on_cast(self, state, caster, cast):
        c = state.champions[caster]
        p = self.params
        state.spawn_projectile(self.ability_id, caster, c.x, c.y, cast.dir_x, cast.dir_y, p.speed, p.radius, p.damage, p.range)

    def on_tick(self, state, proj):
        advance_linear(proj)

    def on_hit(self, state, proj, target):
        state.deal_damage(target, proj.damage)  # stays alive: pierces


class Blink(Ability):
    """Instantly teleports the caster up to `range` units toward the aim point."""

    ability_id = "blink"

    def on_cast(self, state, caster, cast):
        c = state.champions[caster]
        r = self.sim.champion_radius
        c.x = min(max(c.x + cast.dir_x * self.params.range, r), self.sim.width - r)
        c.y = min(max(c.y + cast.dir_y * self.params.range, r), self.sim.height - r)
        c.has_target = False


LANCE = AbilityStats(cooldown=3.0, cast_time=0.0, speed=600.0, range=1000.0, radius=25.0, damage=1)
BLINK = AbilityStats(cooldown=8.0, cast_time=0.0, speed=0.0, range=300.0, radius=0.0, damage=0)
TYPES = {**ABILITY_TYPES, "lance": Lance, "blink": Blink}
CONFIG = replace(
    DEFAULT_CONFIG,
    loadout=("bolt", "lance", "blink"),
    abilities={"bolt": BOLT, "lance": LANCE, "blink": BLINK},
    pickup_pool=(),
)


def cast(aid, x, y):
    return Action(cast=Cast(aid, Vec2(x, y)))


def new_game(spawns):
    return Game(CONFIG, 0, spawns, ability_types=TYPES)


def test_piercing_projectile_hits_once_and_keeps_flying():
    game = new_game(((200.0, 400.0), (500.0, 400.0)))
    run(game, 1, cast("lance", 1100, 400))
    run(game, 20)  # 20 units/tick: passes through the enemy over several ticks
    assert game.state.champions[1].hp == 2
    (proj,) = game.state.projectiles
    assert proj.x > 500 + 60  # beyond the enemy, still alive


def test_blink_teleports_and_is_clamped():
    game = new_game(((200.0, 400.0), (900.0, 400.0)))
    run(game, 1, cast("blink", 200, 1000))  # straight down, 300 units, but the wall is at 770
    me = game.state.champions[0]
    assert (me.x, me.y) == pytest.approx((200.0, 700.0))
    run(game, 1, cast("blink", 200, -1000))  # on cooldown: ignored
    assert me.y == pytest.approx(700.0)


def test_loadout_shows_up_in_observations_with_separate_cooldowns():
    game = new_game(((200.0, 400.0), (900.0, 400.0)))
    run(game, 1, cast("lance", 900, 400))
    cds = game.observe(0).me.cooldowns
    assert set(cds) == {"bolt", "lance", "blink"}
    assert cds["bolt"] == 0.0 and cds["lance"] > 2.9
    assert {p.ability_id for p in game.observe(1).projectiles} == {"lance"}


def test_default_game_is_unchanged_by_extra_types():
    a = Game(DEFAULT_CONFIG, 0)
    b = Game(DEFAULT_CONFIG, 0, ability_types=TYPES)
    for _ in range(50):
        a.step(cast("bolt", 900, 400), cast("bolt", 900, 400))
        b.step(cast("bolt", 900, 400), cast("bolt", 900, 400))
    assert a.state == b.state
