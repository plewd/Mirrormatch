"""Base class for abilities. Each ability is stats (from config) plus hooks.

The sim loop calls the hooks; abilities never need the loop edited:
- on_cast: the cast finished; spawn projectiles or apply effects through the
  GameState helpers (deal_damage, root, shield, interrupt, force_move, ...).
- on_tick: once per tick per projectile this ability owns; move it, set `expired`.
- on_hit: the projectile touched an enemy champion. Set `alive=False` to destroy
  it; a projectile that stays alive (piercing) never hits the same champion twice.
- on_wall_hit: the projectile touched a wall (`wall` given) or left the arena
  (`wall` is None) at contact point (x, y). Default: destroy it.
- on_zone_hit: a zone this ability created detonated over an enemy champion.

Collision detection and the spell-shield check are generic and live in the sim
loop: a shielded target consumes its shield, and the projectile is destroyed
(or the zone's effect skipped) before on_hit / on_zone_hit would run. Hook
defaults are no-ops, so cast-only abilities (dash, shield) implement just on_cast.
"""

from arena.sim.params import AbilityParams, SimParams
from arena.sim.state import CastState, GameState, Projectile, Wall, Zone


class Ability:
    ability_id: str = ""
    targeted: bool = True  # needs an aim point away from the caster
    is_movement: bool = False  # blocked while rooted

    def __init__(self, params: AbilityParams, sim: SimParams) -> None:
        self.params = params  # this ability's stats, in ticks
        self.sim = sim  # arena size, champion stats, etc.

    def on_cast(self, state: GameState, caster: int, cast: CastState) -> None:
        pass

    def on_tick(self, state: GameState, proj: Projectile) -> None:
        pass

    def on_hit(self, state: GameState, proj: Projectile, target: int) -> None:
        pass

    def on_wall_hit(self, state: GameState, proj: Projectile, wall: Wall | None, x: float, y: float) -> None:
        proj.alive = False

    def on_zone_hit(self, state: GameState, zone: Zone, target: int) -> None:
        pass


def advance_linear(proj: Projectile) -> None:
    """Move a projectile straight ahead, stopping exactly at max range."""
    step = min(proj.speed, proj.max_range - proj.traveled)
    proj.prev_x = proj.x
    proj.prev_y = proj.y
    proj.x += proj.dir_x * step
    proj.y += proj.dir_y * step
    proj.traveled += step
    if proj.traveled >= proj.max_range:
        proj.expired = True
