"""Observation encoding and action decoding shared by the RL env and PolicyBot.

Only uses the Observation (canonical frame) plus public config stats, so a
trained policy obeys the same rules as any scripted bot.

Two versions. A saved policy is matched to its encoder by observation size, so
older models keep working:
- v1 (FeatureEncoder): Bolt only, as used by ppo_v1.
- v2 (FeatureEncoderV2): the full kit (dash, statuses, pickups, walls, zones).
- v3 (FeatureEncoderV3): v2 plus the center heal.

v1 action = MultiDiscrete([move, cast, aim]):
- move: 0 keep current target, 1 stop, 2..9 step toward one of 8 compass directions
- cast: 0 no, 1 cast Bolt
- aim:  0..6 angular offsets around the lead-predicted intercept, 7 the enemy's current position
"""

import math

import numpy as np

from arena.bots.common import predict_intercept
from arena.config import GameConfig
from arena.fairness import rotate_about
from arena.sim.types import Action, Cast, ChampionView, Observation, Vec2

N_MOVE = 10
MOVE_KEEP = 0
MOVE_STOP = 1
MOVE_STEP = 150.0  # units ahead to place a directional move target
AIM_OFFSETS_DEG = (-30.0, -15.0, -7.0, 0.0, 7.0, 15.0, 30.0)
AIM_CURRENT = len(AIM_OFFSETS_DEG)
ACTION_NVEC = (N_MOVE, 2, len(AIM_OFFSETS_DEG) + 1)

MAX_PROJECTILES = 6
CHAMP_FEATURES = 8
PROJ_FEATURES = 8
OBS_SIZE = 2 * CHAMP_FEATURES + 3 + MAX_PROJECTILES * PROJ_FEATURES + 1

_DIRS = tuple((math.cos(k * math.pi / 4), math.sin(k * math.pi / 4)) for k in range(8))


class FeatureEncoder:
    obs_size = OBS_SIZE
    action_nvec = ACTION_NVEC

    def __init__(self, config: GameConfig) -> None:
        self.config = config
        self.bolt = config.abilities["bolt"]
        self.w = config.arena_width
        self.h = config.arena_height
        self.diag = math.hypot(self.w, self.h)
        self.hit_dist = config.champion_radius + self.bolt.radius

    def _champ(self, c: ChampionView, out: list[float]) -> None:
        cfg = self.config
        out += (
            2.0 * c.pos.x / self.w - 1.0,
            2.0 * c.pos.y / self.h - 1.0,
            c.vel.x / cfg.champion_speed,
            c.vel.y / cfg.champion_speed,
            c.hp / cfg.champion_hp,
            c.cooldowns["bolt"] / self.bolt.cooldown,
            0.0 if c.cast_ability is None else 1.0,
            c.cast_remaining / self.bolt.cast_time if self.bolt.cast_time > 0 else 0.0,
        )

    def encode(self, obs: Observation) -> np.ndarray:
        out: list[float] = []
        me, en = obs.me.pos, obs.enemy.pos
        self._champ(obs.me, out)
        self._champ(obs.enemy, out)
        out += ((en.x - me.x) / self.w, (en.y - me.y) / self.h, math.hypot(en.x - me.x, en.y - me.y) / self.diag)

        projs = sorted(obs.projectiles, key=lambda p: (p.pos.x - me.x) ** 2 + (p.pos.y - me.y) ** 2)
        for p in projs[:MAX_PROJECTILES]:
            rx, ry = me.x - p.pos.x, me.y - p.pos.y
            speed = math.hypot(p.vel.x, p.vel.y) or 1.0
            dx, dy = p.vel.x / speed, p.vel.y / speed
            along = rx * dx + ry * dy  # distance until closest approach (negative = passed)
            offset = dx * ry - dy * rx  # signed miss distance
            out += (
                1.0,
                -rx / self.w,
                -ry / self.h,
                p.vel.x / self.bolt.speed,
                p.vel.y / self.bolt.speed,
                1.0 if p.is_own else 0.0,
                max(-1.0, min(1.0, along / self.bolt.range)),
                max(-1.0, min(1.0, offset / (3.0 * self.hit_dist))),
            )
        out += [0.0] * (PROJ_FEATURES * (MAX_PROJECTILES - min(len(projs), MAX_PROJECTILES)))
        out.append(obs.time_remaining / self.config.time_limit)
        return np.asarray(out, dtype=np.float32)

    def decode(self, action, obs: Observation) -> Action:
        move_i, cast_i, aim_i = int(action[0]), int(action[1]), int(action[2])
        me = obs.me.pos
        move = None
        if move_i == MOVE_STOP:
            move = me
        elif move_i >= 2:
            dx, dy = _DIRS[move_i - 2]
            move = Vec2(me.x + dx * MOVE_STEP, me.y + dy * MOVE_STEP)
        cast = None
        if cast_i == 1:
            if aim_i == AIM_CURRENT:
                aim = obs.enemy.pos
            else:
                aim = rotate_about(predict_intercept(obs, self.config), me, math.radians(AIM_OFFSETS_DEG[aim_i]))
            cast = Cast("bolt", aim)
        return Action(move=move, cast=cast)


# ---- v2 ----------------------------------------------------------------------
#
# Action = MultiDiscrete([move, ability, aim]):
# - move: as v1
# - ability: 0 none, 1 Bolt, 2 Dash, 3 held item (ignored if empty)
# - aim (8 bins), read per ability:
#     projectiles (bolt, boomerang, root, hook): 0..6 offsets around that ability's
#       lead-predicted intercept, 7 the enemy's current position
#     dash, wall: compass direction 0..7
#     blast: enemy position led by 0, 0.2, ... 1.2 s (bins 0..6), 7 the enemy's current position
#     shield: ignored

ABILITY_NONE, ABILITY_BOLT, ABILITY_DASH, ABILITY_ITEM = range(4)
ACTION_NVEC_V2 = (N_MOVE, 4, 8)
DIRECTIONAL = ("dash", "wall")
BLAST_LEAD_STEP = 0.2  # seconds per aim bin
WALL_OFFSET = 80.0
DASH_AIM = 100.0

MAX_WALLS = 2
MAX_ZONES = 2
MAX_PICKUPS = 2


class FeatureEncoderV2:
    action_nvec = ACTION_NVEC_V2

    def __init__(self, config: GameConfig) -> None:
        self.config = config
        self.w = config.arena_width
        self.h = config.arena_height
        self.diag = math.hypot(self.w, self.h)
        self.abilities = config.loadout + config.pickup_pool  # one-hot order for casts
        self.items = config.pickup_pool  # one-hot order for held items and pickups
        self.thrown = tuple(a for a in self.abilities if config.abilities[a].speed > 0)  # projectile kinds
        self.bolt = config.abilities["bolt"]
        self.max_speed = max(config.abilities[a].speed for a in self.thrown)
        self.champ_features = 4 + 1 + len(config.loadout) + 2 + len(self.abilities) + 3 + len(self.items) + 1
        self.proj_features = 8 + len(self.thrown)
        self.obs_size = (
            2 * self.champ_features + 3
            + MAX_PROJECTILES * self.proj_features
            + MAX_WALLS * 6 + MAX_ZONES * 6 + MAX_PICKUPS * (3 + len(self.items))
            + 1
        )

    def _onehot(self, value, options, out: list[float]) -> None:
        out += [1.0 if value == o else 0.0 for o in options]

    def _rel(self, pos: Vec2, me: Vec2) -> tuple[float, float]:
        return (pos.x - me.x) / self.w, (pos.y - me.y) / self.h

    def _champ(self, c: ChampionView, out: list[float]) -> None:
        cfg = self.config
        out += (
            2.0 * c.pos.x / self.w - 1.0,
            2.0 * c.pos.y / self.h - 1.0,
            c.vel.x / cfg.champion_speed,
            c.vel.y / cfg.champion_speed,
            c.hp / cfg.champion_hp,
        )
        for aid in cfg.loadout:
            cd = cfg.abilities[aid].cooldown
            out.append(c.cooldowns[aid] / cd if cd > 0 else 0.0)
        out += (0.0 if c.cast_ability is None else 1.0, min(c.cast_remaining, 1.0))
        self._onehot(c.cast_ability, self.abilities, out)
        out += (min(c.rooted, 1.0), min(c.shielded, 1.0), 1.0 if c.forced else 0.0)
        self._onehot(c.item, self.items, out)
        out.append(0.0 if c.item is None else 1.0)

    def encode(self, obs: Observation) -> np.ndarray:
        out: list[float] = []
        me, en = obs.me.pos, obs.enemy.pos
        self._champ(obs.me, out)
        self._champ(obs.enemy, out)
        out += (*self._rel(en, me), math.hypot(en.x - me.x, en.y - me.y) / self.diag)

        def near(items, key):
            return sorted(items, key=lambda it: (key(it).x - me.x) ** 2 + (key(it).y - me.y) ** 2)

        hit_dist = self.config.champion_radius + self.bolt.radius
        projs = near(obs.projectiles, lambda p: p.pos)[:MAX_PROJECTILES]
        for p in projs:
            rx, ry = me.x - p.pos.x, me.y - p.pos.y
            speed = math.hypot(p.vel.x, p.vel.y) or 1.0
            dx, dy = p.vel.x / speed, p.vel.y / speed
            along = rx * dx + ry * dy
            offset = dx * ry - dy * rx
            out += (
                1.0, -rx / self.w, -ry / self.h,
                p.vel.x / self.max_speed, p.vel.y / self.max_speed,
                1.0 if p.is_own else 0.0,
                max(-1.0, min(1.0, along / self.bolt.range)),
                max(-1.0, min(1.0, offset / (3.0 * hit_dist))),
            )
            self._onehot(p.ability_id, self.thrown, out)
        out += [0.0] * (self.proj_features * (MAX_PROJECTILES - len(projs)))

        walls = near(obs.walls, lambda wl: Vec2((wl.a.x + wl.b.x) / 2, (wl.a.y + wl.b.y) / 2))[:MAX_WALLS]
        for wl in walls:
            out += (1.0, *self._rel(wl.a, me), *self._rel(wl.b, me), min(wl.remaining, 3.0) / 3.0)
        out += [0.0] * (6 * (MAX_WALLS - len(walls)))

        zones = near(obs.zones, lambda z: z.pos)[:MAX_ZONES]
        for z in zones:
            out += (1.0, *self._rel(z.pos, me), z.radius / 200.0, min(z.remaining, 1.0), 1.0 if z.is_own else 0.0)
        out += [0.0] * (6 * (MAX_ZONES - len(zones)))

        pickups = near(obs.pickups, lambda pk: pk.pos)[:MAX_PICKUPS]
        for pk in pickups:
            out += (1.0, *self._rel(pk.pos, me))
            self._onehot(pk.ability_id, self.items, out)
        out += [0.0] * ((3 + len(self.items)) * (MAX_PICKUPS - len(pickups)))

        out.append(obs.time_remaining / self.config.time_limit)
        return np.asarray(out, dtype=np.float32)

    def decode(self, action, obs: Observation) -> Action:
        move_i, ab_i, aim_i = int(action[0]), int(action[1]), int(action[2])
        me = obs.me.pos
        move = None
        if move_i == MOVE_STOP:
            move = me
        elif move_i >= 2:
            dx, dy = _DIRS[move_i - 2]
            move = Vec2(me.x + dx * MOVE_STEP, me.y + dy * MOVE_STEP)

        aid = {ABILITY_BOLT: "bolt", ABILITY_DASH: "dash", ABILITY_ITEM: obs.me.item}.get(ab_i)
        if aid is None:
            return Action(move=move)
        if aid in DIRECTIONAL:
            dx, dy = _DIRS[aim_i]
            reach = DASH_AIM if aid == "dash" else WALL_OFFSET
            aim = Vec2(me.x + dx * reach, me.y + dy * reach)
        elif aid == "blast":
            e = obs.enemy
            lead = 0.0 if aim_i == AIM_CURRENT else aim_i * BLAST_LEAD_STEP
            aim = Vec2(e.pos.x + e.vel.x * lead, e.pos.y + e.vel.y * lead)
        elif self.config.abilities[aid].speed > 0:
            if aim_i == AIM_CURRENT:
                aim = obs.enemy.pos
            else:
                base = predict_intercept(obs, self.config, aid)
                aim = rotate_about(base, me, math.radians(AIM_OFFSETS_DEG[aim_i]))
        else:  # untargeted (shield)
            aim = me
        return Action(move=move, cast=Cast(aid, aim))


# ---- v3 ----------------------------------------------------------------------
#
# v2 plus the center heal, appended at the end (so a v2 network can be widened
# into a v3 one by adding zero weights for the new inputs). Same actions as v2.

HEAL_FEATURES = 4
HEAL_IN_CAP = 15.0  # seconds; the countdown is only informative this close


class FeatureEncoderV3(FeatureEncoderV2):
    def __init__(self, config: GameConfig) -> None:
        super().__init__(config)
        self.obs_size += HEAL_FEATURES
        self.center = Vec2(self.w / 2, self.h / 2)

    def encode(self, obs: Observation) -> np.ndarray:
        base = super().encode(obs)
        rx, ry = self._rel(self.center, obs.me.pos)
        heal = (1.0 if obs.heal is not None else 0.0, rx, ry, min(obs.heal_in, HEAL_IN_CAP) / HEAL_IN_CAP)
        return np.concatenate((base, np.asarray(heal, dtype=np.float32)))


ENCODERS = {"v1": FeatureEncoder, "v2": FeatureEncoderV2, "v3": FeatureEncoderV3}


def encoder_for_obs_size(size: int, config: GameConfig):
    """Pick the encoder a saved policy was trained with, by its input size."""
    for cls in ENCODERS.values():
        enc = cls(config)
        if enc.obs_size == size:
            return enc
    raise ValueError(f"no feature encoder produces {size} features")
