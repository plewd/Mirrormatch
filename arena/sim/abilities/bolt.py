"""Bolt: a linear skillshot that hits the first enemy it touches."""

from arena.sim.abilities.base import Ability, advance_linear
from arena.sim.state import CastState, GameState, Projectile


class Bolt(Ability):
    ability_id = "bolt"

    def on_cast(self, state: GameState, caster: int, cast: CastState) -> None:
        champ = state.champions[caster]
        p = self.params
        state.spawn_projectile(
            self.ability_id, caster, champ.x, champ.y, cast.dir_x, cast.dir_y,
            p.speed, p.radius, p.damage, p.range,
        )

    def on_tick(self, state: GameState, proj: Projectile) -> None:
        advance_linear(proj)

    def on_hit(self, state: GameState, proj: Projectile, target: int) -> None:
        state.deal_damage(target, proj.damage)
        proj.alive = False
