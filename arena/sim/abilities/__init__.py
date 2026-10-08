"""Registry of ability behavior classes. To add an ability: create its file here,
add it to ABILITY_TYPES, and add its stats to `arena/config.py`."""

from arena.sim.abilities.base import Ability
from arena.sim.abilities.blast import Blast
from arena.sim.abilities.bolt import Bolt
from arena.sim.abilities.boomerang import Boomerang
from arena.sim.abilities.dash import Dash
from arena.sim.abilities.hook import Hook
from arena.sim.abilities.root import RootShot
from arena.sim.abilities.shield import Shield
from arena.sim.abilities.wall import WallAbility

ABILITY_TYPES: dict[str, type[Ability]] = {
    Bolt.ability_id: Bolt,
    Dash.ability_id: Dash,
    Boomerang.ability_id: Boomerang,
    Shield.ability_id: Shield,
    RootShot.ability_id: RootShot,
    WallAbility.ability_id: WallAbility,
    Hook.ability_id: Hook,
    Blast.ability_id: Blast,
}
