"""Hook: a long, narrow skillshot. On an enemy, it yanks them to the caster and
interrupts their cast. On a wall or the arena edge, it pulls the caster there."""

import math

from arena.sim.abilities.base import Ability, advance_linear
from arena.sim.state import CastState, GameState, Projectile, Wall

GAP = 4.0  # space left between the two bodies after a pull


class Hook(Ability):
    ability_id = "hook"

    def on_cast(self, state: GameState, caster: int, cast: CastState) -> None:
        champ = state.champions[caster]
        p = self.params
        state.spawn_projectile(
            self.ability_id, caster, champ.x, champ.y, cast.dir_x, cast.dir_y,
            p.speed, p.radius, 0, p.range,
        )

    def on_tick(self, state: GameState, proj: Projectile) -> None:
        advance_linear(proj)

    def _pull(self, state: GameState, who: int, to_x: float, to_y: float, stop_short: float) -> None:
        champ = state.champions[who]
        dx = to_x - champ.x
        dy = to_y - champ.y
        d = math.hypot(dx, dy)
        if d > stop_short:
            state.force_move(who, dx / d, dy / d, self.params.move_speed, d - stop_short)

    def on_hit(self, state: GameState, proj: Projectile, target: int) -> None:
        caster = state.champions[proj.owner]
        self._pull(state, target, caster.x, caster.y, 2 * self.sim.champion_radius + GAP)  # interrupts their cast
        proj.alive = False

    def on_wall_hit(self, state: GameState, proj: Projectile, wall: Wall | None, x: float, y: float) -> None:
        self._pull(state, proj.owner, x, y, self.sim.champion_radius)
        proj.alive = False
