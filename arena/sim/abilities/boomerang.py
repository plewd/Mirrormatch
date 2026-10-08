"""Boomerang: flies out to max range, then homes back to the caster. It passes
through champions and can hit the enemy once on the way out and once on the way
back. It also turns around early if it reaches the arena edge."""

import math

from arena.sim.abilities.base import Ability, advance_linear
from arena.sim.state import CastState, GameState, Projectile, Wall

OUTBOUND = 0
RETURNING = 1
MAX_RETURN_TRAVEL = 3000.0  # safety cap so a boomerang chasing a dashing caster can't live forever


class Boomerang(Ability):
    ability_id = "boomerang"

    def on_cast(self, state: GameState, caster: int, cast: CastState) -> None:
        champ = state.champions[caster]
        p = self.params
        state.spawn_projectile(
            self.ability_id, caster, champ.x, champ.y, cast.dir_x, cast.dir_y,
            p.speed, p.radius, p.damage, p.range,
        )

    def _turn(self, proj: Projectile) -> None:
        proj.phase = RETURNING
        proj.hit_mask = 0  # may hit the enemy again on the way back
        proj.expired = False

    def on_tick(self, state: GameState, proj: Projectile) -> None:
        if proj.phase == OUTBOUND:
            advance_linear(proj)
            if proj.expired:
                self._turn(proj)
            return
        owner = state.champions[proj.owner]
        dx = owner.x - proj.x
        dy = owner.y - proj.y
        d = math.hypot(dx, dy)
        proj.prev_x = proj.x
        proj.prev_y = proj.y
        if d <= proj.speed or proj.traveled > proj.max_range + MAX_RETURN_TRAVEL:
            proj.x, proj.y = owner.x, owner.y
            proj.expired = True  # caught (removed after this tick's collision check)
            return
        proj.dir_x = dx / d
        proj.dir_y = dy / d
        proj.x += proj.dir_x * proj.speed
        proj.y += proj.dir_y * proj.speed
        proj.traveled += proj.speed

    def on_hit(self, state: GameState, proj: Projectile, target: int) -> None:
        state.deal_damage(target, proj.damage)  # keeps flying

    def on_wall_hit(self, state: GameState, proj: Projectile, wall: Wall | None, x: float, y: float) -> None:
        if wall is not None:
            proj.alive = False  # walls block it
            return
        # Arena edge: come back. It may already have turned this tick at max range;
        # clamp so float error in the contact point can't leave it just outside.
        proj.x = min(max(x, 0.0), self.sim.width)
        proj.y = min(max(y, 0.0), self.sim.height)
        if proj.phase == OUTBOUND:
            self._turn(proj)
