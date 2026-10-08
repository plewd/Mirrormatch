"""The controller-facing types: what a controller sees and what it returns.

Observations are in the player's canonical (mirrored) frame: every player sees
itself as the left-side spawner. Velocities are in units/sec and durations in
seconds, so controllers don't depend on the tick rate.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Vec2:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Cast:
    ability_id: str
    aim: Vec2


@dataclass(frozen=True, slots=True)
class Action:
    move: Vec2 | None = None
    cast: Cast | None = None


NOOP = Action()


@dataclass(frozen=True, slots=True)
class ChampionView:
    pos: Vec2
    vel: Vec2
    hp: int
    cooldowns: dict[str, float]  # ability id -> seconds until castable
    cast_ability: str | None  # ability being cast, if any
    cast_remaining: float  # seconds until the current cast fires (0 if not casting)
    rooted: float = 0.0  # seconds of root left
    shielded: float = 0.0  # seconds of spell shield left
    forced: bool = False  # mid-dash or being pulled
    item: str | None = None  # held pickup ability id


@dataclass(frozen=True, slots=True)
class ProjectileView:
    pos: Vec2
    vel: Vec2
    is_own: bool
    ability_id: str


@dataclass(frozen=True, slots=True)
class WallView:
    a: Vec2
    b: Vec2
    remaining: float  # seconds
    is_own: bool


@dataclass(frozen=True, slots=True)
class ZoneView:
    pos: Vec2
    radius: float
    remaining: float  # seconds until it detonates
    is_own: bool
    ability_id: str


@dataclass(frozen=True, slots=True)
class PickupView:
    pos: Vec2
    ability_id: str


@dataclass(frozen=True, slots=True)
class Observation:
    me: ChampionView
    enemy: ChampionView
    projectiles: tuple[ProjectileView, ...]
    time_remaining: float  # seconds
    walls: tuple[WallView, ...] = ()
    pickups: tuple[PickupView, ...] = ()
    zones: tuple[ZoneView, ...] = ()
    heal: Vec2 | None = None  # the center heal orb, when it's up
    heal_in: float = 99.0  # seconds until it appears (0 while it's up); the default means "not soon"
