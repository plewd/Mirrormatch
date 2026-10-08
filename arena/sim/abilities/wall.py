"""Wall: a short-lived segment, centered on the aim point (clamped to placement
range) and perpendicular to the aim. It blocks every projectile, both sides',
but not movement. Standing in it doesn't protect you: a projectile reaches
your body before the wall line."""

import math

from arena.sim.abilities.base import Ability
from arena.sim.state import CastState, GameState, Wall


class WallAbility(Ability):
    ability_id = "wall"

    def on_cast(self, state: GameState, caster: int, cast: CastState) -> None:
        champ = state.champions[caster]
        p = self.params
        dist = min(math.hypot(cast.aim_x - champ.x, cast.aim_y - champ.y), p.range)
        cx = champ.x + cast.dir_x * dist
        cy = champ.y + cast.dir_y * dist
        hx = -cast.dir_y * p.length / 2  # half-extent along the wall
        hy = cast.dir_x * p.length / 2
        state.walls.append(Wall(cx - hx, cy - hy, cx + hx, cy + hy, caster, p.duration_ticks))
