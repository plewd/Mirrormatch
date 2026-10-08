"""Charged blast: a long, rooting cast, then a telegraphed circle at the aim point
(clamped to range) that damages enemies inside it when its fuse runs out."""

import math

from arena.sim.abilities.base import Ability
from arena.sim.state import CastState, GameState, Zone


class Blast(Ability):
    ability_id = "blast"

    def on_cast(self, state: GameState, caster: int, cast: CastState) -> None:
        champ = state.champions[caster]
        p = self.params
        dist = min(math.hypot(cast.aim_x - champ.x, cast.aim_y - champ.y), p.range)
        state.zones.append(Zone(
            self.ability_id, caster,
            champ.x + cast.dir_x * dist, champ.y + cast.dir_y * dist,
            p.radius, p.damage, p.duration_ticks,
        ))

    def on_zone_hit(self, state: GameState, zone: Zone, target: int) -> None:
        state.deal_damage(target, zone.damage)
