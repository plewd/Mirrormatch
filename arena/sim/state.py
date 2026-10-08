"""Mutable sim state. World coordinates, units per tick, durations in ticks."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class CastState:
    ability_id: str
    ticks_remaining: int  # ticks the caster stays rooted before the effect fires
    dir_x: float  # aim direction, unit vector, locked at cast start
    dir_y: float
    aim_x: float  # aim point (world), locked at cast start
    aim_y: float


@dataclass(slots=True)
class ForcedMove:
    """Movement that overrides the move target (dashes, pulls)."""

    dir_x: float
    dir_y: float
    speed: float  # units/tick
    remaining: float  # units left to travel


@dataclass(slots=True)
class Champion:
    x: float
    y: float
    hp: int
    cooldowns: dict[str, int]  # loadout ability id -> ticks until castable
    vx: float = 0.0  # displacement during the last tick
    vy: float = 0.0
    has_target: bool = False
    target_x: float = 0.0
    target_y: float = 0.0
    cast: CastState | None = None
    forced: ForcedMove | None = None  # no moving or casting while set
    root_ticks: int = 0  # no moving or dashing while > 0
    shield_ticks: int = 0  # blocks the next enemy ability effect while > 0
    shield_heal: int = 0  # HP the current shield restores when it blocks
    item: str | None = None  # held pickup ability id


@dataclass(slots=True)
class Projectile:
    pid: int
    ability_id: str
    owner: int
    x: float
    y: float
    dir_x: float
    dir_y: float
    speed: float  # units/tick
    radius: float
    damage: int
    max_range: float
    prev_x: float = 0.0  # position at the start of this tick, for swept collision
    prev_y: float = 0.0
    traveled: float = 0.0
    expired: bool = False  # reached max range; removed after this tick's collision check
    alive: bool = True  # cleared by on_hit to destroy the projectile
    hit_mask: int = 0  # bit i set once champion i has been hit, so piercing hits land once
    phase: int = 0  # free for ability use (e.g. boomerang outbound/returning)


@dataclass(slots=True)
class Wall:
    """A segment that blocks all projectiles (not movement) until it expires."""

    ax: float
    ay: float
    bx: float
    by: float
    owner: int
    ticks_remaining: int


@dataclass(slots=True)
class Zone:
    """A telegraphed circle that triggers its ability's on_zone_hit on every enemy
    champion overlapping it when its fuse runs out."""

    ability_id: str
    owner: int
    x: float
    y: float
    radius: float
    damage: int
    ticks_remaining: int


@dataclass(slots=True)
class Pickup:
    x: float
    y: float
    ability_id: str


@dataclass(slots=True)
class GameState:
    tick: int
    champions: list[Champion]
    projectiles: list[Projectile] = field(default_factory=list)
    next_pid: int = 0
    walls: list[Wall] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    pickups: list[Pickup] = field(default_factory=list)
    next_pickup_tick: int = 0
    heal_up: bool = False  # the center heal orb is available
    next_heal_tick: int = 0
    pending_damage: list[tuple[int, int, str, int]] = field(default_factory=list)  # (target, amount, ability, source)
    # What happened this tick, for stats and tools; cleared at the start of every step. Tuples:
    # ("cast", player, ability) ("hit", source, target, ability) ("damage", source, target, ability, amount)
    # ("blocked", target, source, ability) ("pickup", player, ability) ("heal", player, hp_gained)
    events: list[tuple] = field(default_factory=list)
    acting: tuple[int, str] | None = None  # (owner, ability) whose hit hook is running, so damage knows its source
    done: bool = False
    winner: int | None = None  # None with done=True means draw

    def spawn_projectile(
        self,
        ability_id: str,
        owner: int,
        x: float,
        y: float,
        dir_x: float,
        dir_y: float,
        speed: float,
        radius: float,
        damage: int,
        max_range: float,
    ) -> Projectile:
        proj = Projectile(
            pid=self.next_pid,
            ability_id=ability_id,
            owner=owner,
            x=x,
            y=y,
            dir_x=dir_x,
            dir_y=dir_y,
            speed=speed,
            radius=radius,
            damage=damage,
            max_range=max_range,
            prev_x=x,
            prev_y=y,
        )
        self.next_pid += 1
        self.projectiles.append(proj)
        return proj

    # ---- effects abilities apply. The shield check happens in the loop, before
    # on_hit / on_zone_hit run, so these never need to check it themselves.

    def deal_damage(self, target: int, amount: int) -> None:
        """Queue damage; it is applied to both players at once at the end of the tick."""
        source, ability = self.acting if self.acting is not None else (-1, "")
        self.pending_damage.append((target, amount, ability, source))

    def root(self, target: int, ticks: int) -> None:
        champ = self.champions[target]
        champ.root_ticks = max(champ.root_ticks, ticks)

    def shield(self, target: int, ticks: int, heal: int = 0) -> None:
        """Spell shield for `ticks`: blocks the next enemy ability effect, then heals `heal` HP."""
        champ = self.champions[target]
        champ.shield_ticks = max(champ.shield_ticks, ticks)
        champ.shield_heal = heal

    def interrupt(self, target: int) -> None:
        """Cancel a cast in progress. Its cooldown stays spent."""
        self.champions[target].cast = None

    def force_move(self, target: int, dir_x: float, dir_y: float, speed: float, distance: float) -> None:
        """Move a champion `distance` units along a unit direction. Overrides its
        move target (cleared) and root, interrupts any cast in progress (no casting
        while forced), and stops early at the arena edge."""
        champ = self.champions[target]
        champ.forced = ForcedMove(dir_x, dir_y, speed, distance)
        champ.has_target = False
        champ.cast = None
