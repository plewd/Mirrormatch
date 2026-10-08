"""Dash: a short, fast, unsteerable burst toward the aim point (always full distance)."""

from arena.sim.abilities.base import Ability
from arena.sim.state import CastState, GameState


class Dash(Ability):
    ability_id = "dash"
    is_movement = True

    def on_cast(self, state: GameState, caster: int, cast: CastState) -> None:
        p = self.params
        state.force_move(caster, cast.dir_x, cast.dir_y, p.move_speed, p.range)
