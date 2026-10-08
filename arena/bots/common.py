"""Helpers shared by scripted bots. Everything here works on Observations only,
plus public game stats from the config."""

import math

from arena.config import GameConfig
from arena.sim.types import Cast, Observation, ProjectileView, Vec2


def dist(a: Vec2, b: Vec2) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def can_cast(obs: Observation, ability_id: str) -> bool:
    return obs.me.cast_ability is None and obs.me.cooldowns[ability_id] <= 0.0


def clamp_to_arena(p: Vec2, config: GameConfig) -> Vec2:
    r = config.champion_radius
    return Vec2(
        min(max(p.x, r), config.arena_width - r),
        min(max(p.y, r), config.arena_height - r),
    )


def predict_intercept(obs: Observation, config: GameConfig, ability_id: str = "bolt") -> Vec2:
    """Where to aim so a projectile meets the enemy, assuming the enemy keeps its
    current velocity through our cast time and the projectile's flight."""
    stats = config.abilities[ability_id]
    me = obs.me.pos
    e = obs.enemy.pos
    v = obs.enemy.vel
    aim = e
    for _ in range(4):  # fixed-point iteration converges quickly when bolt >> champion speed
        t = stats.cast_time + dist(me, aim) / stats.speed
        aim = clamp_to_arena(Vec2(e.x + v.x * t, e.y + v.y * t), config)
    return aim


# Held items a bot can throw like a Bolt (aimed at the predicted intercept).
PROJECTILE_ITEMS = ("boomerang", "root", "hook")

THREAT_MARGIN = 15.0  # extra clearance beyond the touching distance
THREAT_HORIZON = 1.2  # seconds; ignore projectiles further out than this


def incoming_threat(obs: Observation, config: GameConfig) -> tuple[float, ProjectileView, float] | None:
    """The most imminent enemy projectile on a hitting course, assuming it keeps its
    current velocity: (seconds to impact, projectile, signed miss distance)."""
    me = obs.me.pos
    best = None
    for p in obs.projectiles:
        if p.is_own:
            continue
        stats = config.abilities[p.ability_id]
        speed = math.hypot(p.vel.x, p.vel.y)
        if speed == 0.0:
            continue
        dx, dy = p.vel.x / speed, p.vel.y / speed
        rx, ry = me.x - p.pos.x, me.y - p.pos.y
        along = rx * dx + ry * dy
        if along < -config.champion_radius or along > stats.range:
            continue
        offset = dx * ry - dy * rx  # signed perpendicular distance from the path
        if abs(offset) >= config.champion_radius + stats.radius + THREAT_MARGIN:
            continue
        t = max(along, 0.0) / speed
        if t <= THREAT_HORIZON and (best is None or t < best[0]):
            best = (t, p, offset)
    return best


def blast_cast(obs: Observation, config: GameConfig) -> Cast | None:
    """Drop a held blast where the enemy will roughly be. Aims dead-on at enemies
    that can't walk (rooted, casting, or being moved), otherwise leads a little."""
    if obs.me.item != "blast" or obs.me.cast_ability is not None:
        return None
    e = obs.enemy
    stuck = e.rooted > 0.0 or e.cast_ability is not None or e.forced
    lead = 0.0 if stuck else 0.4
    aim = clamp_to_arena(Vec2(e.pos.x + e.vel.x * lead, e.pos.y + e.vel.y * lead), config)
    if dist(obs.me.pos, aim) > config.abilities["blast"].range:
        return None
    return Cast("blast", aim)


def wall_block(obs: Observation, proj: ProjectileView) -> Cast | None:
    """Put a held wall between us and an incoming projectile."""
    if obs.me.item != "wall" or obs.me.cast_ability is not None or obs.me.forced:
        return None
    dx, dy = proj.pos.x - obs.me.pos.x, proj.pos.y - obs.me.pos.y
    d = math.hypot(dx, dy)
    if d < 1.0:
        return None
    k = min(80.0, d * 0.5) / d
    return Cast("wall", Vec2(obs.me.pos.x + dx * k, obs.me.pos.y + dy * k))


DODGE_STEP = 160.0  # how far to step sideways
DASH_IF_WALK_COVERS = 0.7  # walking "can't make it" below this share of the needed clearance


def dodge_target(obs: Observation, config: GameConfig, proj: ProjectileView, offset: float) -> Vec2:
    """A point perpendicular to the projectile's path: the side we're already
    off-line on, unless a wall leaves more room on the other side."""
    me = obs.me.pos
    speed = math.hypot(proj.vel.x, proj.vel.y)
    if speed < 1e-9:  # no direction to step away from (e.g. both champions on the heal spot): pick one
        nx, ny = 0.0, 1.0
    else:
        nx, ny = -proj.vel.y / speed, proj.vel.x / speed  # unit normal; offset is measured along it
    preferred = 1.0 if offset >= 0.0 else -1.0
    best_target, best_clear = me, -math.inf
    for side in (preferred, -preferred):
        target = clamp_to_arena(Vec2(me.x + nx * side * DODGE_STEP, me.y + ny * side * DODGE_STEP), config)
        moved = (target.x - me.x) * nx * side + (target.y - me.y) * ny * side
        clearance = offset * side + moved
        if clearance > best_clear + 1e-6:  # strictly better, so ties keep the preferred side
            best_target, best_clear = target, clearance
    return best_target


def can_sidestep(obs: Observation, config: GameConfig, threat: tuple[float, ProjectileView, float]) -> bool:
    """Whether walking alone clears this threat in time."""
    t, proj, offset = threat
    if obs.me.rooted > 0.0:
        return False
    need = config.champion_radius + config.abilities[proj.ability_id].radius + THREAT_MARGIN - abs(offset)
    return config.champion_speed * t >= need / DASH_IF_WALK_COVERS


HEAL_CONTEST_SLACK = 60.0  # go for an available heal unless the enemy is clearly closer
HEAL_PREPOSITION = (1.5, 450.0)  # head to the center this many seconds early, if within this distance


def heal_spot(config: GameConfig) -> Vec2:
    return Vec2(config.arena_width / 2, config.arena_height / 2)


def heal_move(obs: Observation, config: GameConfig) -> Vec2 | None:
    """Walk to the center heal when it's up and contestable, or just before it appears."""
    spot = heal_spot(config)
    d_me, d_enemy = dist(obs.me.pos, spot), dist(obs.enemy.pos, spot)
    if obs.heal is not None:
        return spot if d_me <= d_enemy + HEAL_CONTEST_SLACK else None
    soon, near = HEAL_PREPOSITION
    return spot if obs.heal_in < soon and d_me < near else None


def shield_cast(obs: Observation) -> Cast | None:
    """Raise a held spell shield (instant, self-cast)."""
    if obs.me.item == "shield" and obs.me.cast_ability is None and not obs.me.forced:
        return Cast("shield", obs.me.pos)
    return None


def contested_pickup(obs: Observation, max_dist: float) -> Vec2 | None:
    """The nearest pickup we're closer to than the enemy, if within max_dist."""
    if obs.me.item is not None:
        return None
    best, best_d = None, max_dist
    for pk in obs.pickups:
        d = dist(obs.me.pos, pk.pos)
        if d < best_d and d < dist(obs.enemy.pos, pk.pos):
            best, best_d = pk.pos, d
    return best


def item_shot(obs: Observation, config: GameConfig, range_fraction: float) -> Cast | None:
    """Throw a held projectile item at the predicted intercept, if in range."""
    item = obs.me.item
    if item not in PROJECTILE_ITEMS or obs.me.cast_ability is not None:
        return None
    aim = predict_intercept(obs, config, item)
    if dist(obs.me.pos, aim) > config.abilities[item].range * range_fraction:
        return None
    return Cast(item, aim)
