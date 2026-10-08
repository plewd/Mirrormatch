"""All tunable game numbers live here.

Values are in seconds and world units. The sim converts them to ticks exactly
once, in `arena/sim/params.py`.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AbilityStats:
    """Stats shared by all abilities; each ability uses the ones it needs."""

    cooldown: float = 0.0  # seconds, starts when the cast starts (unused for pickups)
    cast_time: float = 0.0  # seconds the caster is rooted before the effect fires
    speed: float = 0.0  # projectile speed, units/sec
    range: float = 0.0  # max projectile travel / dash distance / placement range, units
    radius: float = 0.0  # projectile half-width or zone radius, units
    damage: int = 0
    duration: float = 0.0  # seconds an effect lasts (root, shield, wall, zone delay)
    length: float = 0.0  # wall length, units
    move_speed: float = 0.0  # forced-movement speed (dash, pulls), units/sec
    heal: int = 0  # HP restored (shield: on each successful block, capped at max HP)


BOLT = AbilityStats(
    cooldown=1.5,
    cast_time=0.25,
    speed=1200.0,
    range=900.0,
    radius=20.0,
    damage=1,
)

DASH = AbilityStats(cooldown=5.0, range=250.0, move_speed=1667.0)  # 250 units in 0.15 s

# Pickups (single use, so no cooldown).
BOOMERANG = AbilityStats(cast_time=0.2, speed=900.0, range=600.0, radius=18.0, damage=1)
SHIELD = AbilityStats(duration=1.5, heal=1)  # instant self-cast; a block also heals
ROOT = AbilityStats(cast_time=0.25, speed=400.0, range=750.0, radius=100.0, duration=0.75)  # a huge slow wave, no damage
WALL = AbilityStats(cast_time=0.1, range=450.0, length=160.0, duration=2.5)  # range = max placement distance
HOOK = AbilityStats(cast_time=0.3, speed=1400.0, range=700.0, radius=15.0, move_speed=1600.0)  # pull speed
BLAST = AbilityStats(cast_time=0.8, range=700.0, radius=110.0, damage=1, duration=0.6)  # duration = fuse


@dataclass(frozen=True)
class GameConfig:
    tick_rate: int = 30
    arena_width: float = 1200.0
    arena_height: float = 800.0
    time_limit: float = 90.0  # seconds; at timeout more HP wins, equal HP is a draw

    champion_radius: float = 30.0
    champion_speed: float = 250.0  # units/sec
    champion_hp: int = 3

    # Ability ids every champion always has (Q, W), and stats for every known ability.
    loadout: tuple[str, ...] = ("bolt", "dash")
    abilities: dict[str, AbilityStats] = field(
        default_factory=lambda: {
            "bolt": BOLT, "dash": DASH, "boomerang": BOOMERANG, "shield": SHIELD, "root": ROOT,
            "wall": WALL, "hook": HOOK, "blast": BLAST,
        }
    )

    # Pickups: one at a time, each on the line equidistant from both champions (fair at the
    # moment it appears), with an ability not already on the map.
    pickup_pool: tuple[str, ...] = ("boomerang", "shield", "root", "wall", "hook", "blast")
    pickup_first_spawn: float = 5.0  # seconds
    pickup_interval: float = 5.0  # seconds between spawns; skipped while the map is full
    pickup_max: int = 2  # pickups on the map at once
    pickup_min_distance: float = 150.0  # spawn at least this far from both champions, when the arena allows
    pickup_radius: float = 20.0

    # Center heal: an orb at the arena center that heals whoever touches it (capped at max HP).
    heal_first_spawn: float = 15.0  # seconds
    heal_respawn: float = 15.0  # seconds after it was taken
    heal_radius: float = 25.0
    heal_amount: int = 1


DEFAULT_CONFIG = GameConfig()


@dataclass(frozen=True)
class Difficulty:
    """Fairness knobs applied to a bot by `arena.fairness.FairController`."""

    reaction_delay: int  # ticks the bot's observations lag behind the game
    rate_limit: int  # the bot decides once every this many ticks
    aim_noise_deg: float  # std of Gaussian angular error added to each aim


DIFFICULTIES: dict[str, Difficulty] = {
    "easy": Difficulty(reaction_delay=10, rate_limit=6, aim_noise_deg=8.0),
    "normal": Difficulty(reaction_delay=6, rate_limit=3, aim_noise_deg=4.0),
    "hard": Difficulty(reaction_delay=3, rate_limit=1, aim_noise_deg=1.5),
}
