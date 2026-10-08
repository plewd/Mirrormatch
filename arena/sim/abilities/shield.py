"""Spell shield: instant self-cast; blocks the next enemy ability effect of any kind,
and a successful block heals (the check itself is in the sim loop)."""

from arena.sim.abilities.base import Ability
from arena.sim.state import CastState, GameState


class Shield(Ability):
    ability_id = "shield"
    targeted = False

    def on_cast(self, state: GameState, caster: int, cast: CastState) -> None:
        state.shield(caster, self.params.duration_ticks, self.params.heal)
