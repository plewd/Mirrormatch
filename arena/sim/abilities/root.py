"""Root shot: a wide, slower skillshot. No damage; roots the first enemy it hits,
which is usually enough time to land a Bolt."""

from arena.sim.abilities.base import Ability, advance_linear
from arena.sim.state import CastState, GameState, Projectile


class RootShot(Ability):
    ability_id = "root"

    def on_cast(self, state: GameState, caster: int, cast: CastState) -> None:
        champ = state.champions[caster]
        p = self.params
        state.spawn_projectile(
            self.ability_id, caster, champ.x, champ.y, cast.dir_x, cast.dir_y,
            p.speed, p.radius, 0, p.range,
        )

    def on_tick(self, state: GameState, proj: Projectile) -> None:
        advance_linear(proj)

    def on_hit(self, state: GameState, proj: Projectile, target: int) -> None:
        state.root(target, self.params.duration_ticks)
        proj.alive = False
