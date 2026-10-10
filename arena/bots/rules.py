"""Rule-list bots: the language behind the block editor.

A bot is an ordered list of rules. Each rule is "if <all conditions> then <action>".
Every action belongs to one of two channels:
- move: where to walk (approach, retreat, strafe, go to pickup, hold, wander)
- ability: what to cast (shoot, dash, use item, hold fire)

- mode: switch the bot's mode (set_mode), which conditions can test (in_mode)

Each decision, the bot runs the first matching rule *per channel*, so it can walk
and shoot at the same time. An action that can't happen right now (shooting on
cooldown, a dash while rooted, using an empty slot) doesn't count as a match, and
the next rule in that channel gets a chance. `hold` and `hold_fire` always match.
A set_mode takes effect immediately, so rules below it already see the new mode.

The bot also remembers a little: when each side last used each ability, when it
last got hit or landed a hit, and how long it has been in its current mode.

Bot file (JSON):
    {"name": "...", "version": 1, "rules": [
        {"if": [<condition>, ...], "then": {"action": "<name>", <params>}}, ...]}
A condition is {"sensor": "<name>", <params>} for yes/no sensors,
{"sensor": "<name>", "op": "<" | ">", "value": <number>, <params>} for number
sensors, {"sensor": "chance", "value": <0-100>} for a random roll each decision,
or {"not": <condition>}. An empty "if" always matches.

Everything is computed from the Observation plus public config stats, like any
other bot. `vocabulary()` describes every sensor and action so the editor can
build its blocks from the same source.
"""

import json
import math
import pathlib
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from arena.bots.common import (
    PROJECTILE_ITEMS, blast_cast, can_cast, can_sidestep, clamp_to_arena, dist, dodge_target,
    heal_spot, incoming_threat, predict_intercept, wall_block,
)
from arena.config import DEFAULT_CONFIG, GameConfig
from arena.sim.types import NOOP, Action, Cast, Observation, ProjectileView, Vec2

VERSION = 1
MAX_RULES = 64
MAX_DEPTH = 4  # nesting of "not"
NO_THREAT_TIME = 99.0  # threat_time when nothing is incoming
NO_PICKUP_DISTANCE = 9999.0
RANGE_FRACTION = 0.85  # "in range" means within this share of max range, like leader
STEP = 150.0  # how far ahead approach / retreat place their target
WANDER_CHANGE = 0.1  # chance per decision that wander picks a new point
NEVER = 99.0  # "seconds since" for something that hasn't happened yet
MODES = ("normal", "aggressive", "defensive", "baiting")
TRACKED = ("bolt", "dash")  # loadout abilities whose use is inferred from cooldown resets
CHANNELS = ("move", "ability", "mode")

KEEP = object()  # an action that matched but issues no command this decision

# Per-rule outcomes of one decision, recorded in RuleBot.trace for the debugger.
FIRED = "fired"  # this rule's action ran
COULDNT = "couldnt"  # conditions held, but the action wasn't possible right now (fell through)
FALSE = "false"  # some condition didn't hold
SKIPPED = "skipped"  # an earlier rule already handled this rule's channel
UNREACHED = "unreached"  # every channel was handled before this rule


# ---- memory --------------------------------------------------------------------


class Memory:
    """What a rule bot remembers between decisions. Times are the game clock
    (time_remaining) at which something happened; it counts down."""

    def __init__(self) -> None:
        self.used: dict[str, dict[str, float]] = {"me": {}, "enemy": {}}
        self.last_cd: dict[str, dict[str, float]] = {"me": {}, "enemy": {}}
        self.last_item: dict[str, str | None] = {"me": None, "enemy": None}
        self.last_hp: dict[str, int | None] = {"me": None, "enemy": None}
        self.was_hit: float | None = None
        self.hit_enemy: float | None = None
        self.mode = MODES[0]
        self.mode_since: float | None = None

    def update(self, obs: Observation, config: GameConfig) -> None:
        now = obs.time_remaining
        if self.mode_since is None:
            self.mode_since = now
        for side, view in (("me", obs.me), ("enemy", obs.enemy)):
            for aid in TRACKED:
                cd = view.cooldowns[aid]
                if cd > self.last_cd[side].get(aid, 0.0) + 1e-9:
                    # The cooldown restarted. Back-date the use by how far it has already run down.
                    self.used[side][aid] = now + (config.abilities[aid].cooldown - cd)
                self.last_cd[side][aid] = cd
            if self.last_item[side] is not None and view.item is None:
                self.used[side]["item"] = now
            self.last_item[side] = view.item
            last = self.last_hp[side]
            if last is not None and view.hp < last:
                if side == "me":
                    self.was_hit = now
                else:
                    self.hit_enemy = now
            self.last_hp[side] = view.hp

    @staticmethod
    def since(t: float | None, now: float) -> float:
        return NEVER if t is None else min(NEVER, t - now)


# ---- per-decision context ----------------------------------------------------


class Context:
    """One decision's view of the game, with expensive lookups computed lazily."""

    def __init__(self, obs: Observation, config: GameConfig, bot: "RuleBot") -> None:
        self.obs = obs
        self.config = config
        self.bot = bot
        self.memory = bot.memory
        self.now = obs.time_remaining

    def since(self, t: float | None) -> float:
        return Memory.since(t, self.now)

    @cached_property
    def threat(self) -> tuple[float, ProjectileView, float] | None:
        return incoming_threat(self.obs, self.config)

    def intercept(self, ability_id: str) -> Vec2:
        return predict_intercept(self.obs, self.config, ability_id)

    @cached_property
    def nearest_pickup(self) -> Vec2 | None:
        me = self.obs.me.pos
        best, best_d = None, math.inf
        for pk in self.obs.pickups:
            d = dist(me, pk.pos)
            if d < best_d:
                best, best_d = pk.pos, d
        return best

    def resolve(self, ability: str) -> str | None:
        """'item' means whatever is held."""
        return self.obs.me.item if ability == "item" else ability


# ---- sensors -----------------------------------------------------------------

ABILITY_CHOICES = ("bolt", "dash", "item")
RANGED_CHOICES = ("bolt", "item")
COOLDOWN_CHOICES = ("bolt", "dash")
AIM_CHOICES = ("lead", "direct")
DASH_CHOICES = ("away_from_threat", "toward_enemy", "away_from_enemy", "to_pickup")


def item_choices(config: GameConfig) -> tuple[str, ...]:
    return ("any",) + config.pickup_pool


@dataclass(frozen=True)
class Sensor:
    kind: str  # "number", "bool", or "percent" (a random roll against a 0-100 value)
    help: str
    params: dict[str, Callable[[GameConfig], tuple[str, ...]]]
    read: Callable[..., float | bool]


def _ready(ctx: Context, ability: str) -> bool:
    me = ctx.obs.me
    if ability == "item":
        return me.item is not None and me.cast_ability is None and not me.forced
    if ability == "dash" and me.rooted > 0.0:
        return False
    return not me.forced and can_cast(ctx.obs, ability)


def _in_range(ctx: Context, ability: str) -> bool:
    aid = ctx.resolve(ability)
    if aid is None:
        return False
    stats = ctx.config.abilities[aid]
    if stats.speed > 0.0:  # projectiles: would a leading shot reach?
        return dist(ctx.obs.me.pos, ctx.intercept(aid)) <= stats.range * RANGE_FRACTION
    if stats.damage > 0:  # placed attacks (blast): is the enemy within placement range?
        return dist(ctx.obs.me.pos, ctx.obs.enemy.pos) <= stats.range
    return False  # shield, wall: not aimed at the enemy, so never "in range"


def _holding(item: str | None, wanted: str) -> bool:
    return item is not None and (wanted == "any" or item == wanted)


def _enemy_ready(ctx: Context, ability: str) -> bool:
    e = ctx.obs.enemy
    if ability == "item":
        return e.item is not None and e.cast_ability is None and not e.forced
    if ability == "dash" and e.rooted > 0.0:
        return False
    return e.cast_ability is None and not e.forced and e.cooldowns[ability] <= 0.0


def _closer_to_pickup(ctx: Context) -> bool:
    me, en = ctx.obs.me.pos, ctx.obs.enemy.pos
    return any(dist(me, pk.pos) < dist(en, pk.pos) for pk in ctx.obs.pickups)


SENSORS: dict[str, Sensor] = {
    "enemy_distance": Sensor("number", "Distance to the enemy, in units (the arena is 1200 x 800).", {},
                             lambda ctx: dist(ctx.obs.me.pos, ctx.obs.enemy.pos)),
    "threat_time": Sensor("number", f"Seconds until an enemy projectile would hit you ({NO_THREAT_TIME:g} if none).", {},
                          lambda ctx: NO_THREAT_TIME if ctx.threat is None else ctx.threat[0]),
    "my_hp": Sensor("number", "Your HP.", {}, lambda ctx: ctx.obs.me.hp),
    "enemy_hp": Sensor("number", "The enemy's HP.", {}, lambda ctx: ctx.obs.enemy.hp),
    "time_left": Sensor("number", "Seconds left in the game.", {}, lambda ctx: ctx.obs.time_remaining),
    "pickup_distance": Sensor("number", f"Distance to the nearest pickup ({NO_PICKUP_DISTANCE:g} if none).", {},
                              lambda ctx: NO_PICKUP_DISTANCE if ctx.nearest_pickup is None
                              else dist(ctx.obs.me.pos, ctx.nearest_pickup)),
    "threatened": Sensor("bool", "An enemy projectile is on course to hit you.", {},
                         lambda ctx: ctx.threat is not None),
    "can_sidestep": Sensor("bool", "Walking alone gets you out of the incoming projectile's way (true if none).", {},
                           lambda ctx: ctx.threat is None or can_sidestep(ctx.obs, ctx.config, ctx.threat)),
    "ready": Sensor("bool", "The ability can be cast right now.", {"ability": lambda cfg: ABILITY_CHOICES},
                    lambda ctx, ability: _ready(ctx, ability)),
    "in_range": Sensor("bool", "An attack on the enemy would reach (false for shield and wall).",
                       {"ability": lambda cfg: RANGED_CHOICES}, lambda ctx, ability: _in_range(ctx, ability)),
    "holding": Sensor("bool", "You hold this pickup.", {"item": item_choices},
                      lambda ctx, item: _holding(ctx.obs.me.item, item)),
    "enemy_holding": Sensor("bool", "The enemy holds this pickup.", {"item": item_choices},
                            lambda ctx, item: _holding(ctx.obs.enemy.item, item)),
    "closer_to_pickup": Sensor("bool", "Some pickup is closer to you than to the enemy.", {}, _closer_to_pickup),
    "heal_up": Sensor("bool", "The center heal is available right now.", {}, lambda ctx: ctx.obs.heal is not None),
    "heal_in": Sensor("number", "Seconds until the center heal appears (0 while it's up).", {},
                      lambda ctx: ctx.obs.heal_in),
    "heal_distance": Sensor("number", "Your distance to the center heal spot.", {},
                            lambda ctx: dist(ctx.obs.me.pos, heal_spot(ctx.config))),
    "closer_to_heal": Sensor("bool", "You are closer to the center heal spot than the enemy is.", {},
                             lambda ctx: dist(ctx.obs.me.pos, heal_spot(ctx.config))
                             < dist(ctx.obs.enemy.pos, heal_spot(ctx.config))),
    "enemy_casting": Sensor("bool", "The enemy is in a cast (rooted until it fires).", {},
                            lambda ctx: ctx.obs.enemy.cast_ability is not None),
    "enemy_rooted": Sensor("bool", "The enemy is rooted.", {}, lambda ctx: ctx.obs.enemy.rooted > 0.0),
    "enemy_shielded": Sensor("bool", "The enemy has a spell shield up.", {}, lambda ctx: ctx.obs.enemy.shielded > 0.0),
    "enemy_dashing": Sensor("bool", "The enemy is mid-dash or being pulled.", {}, lambda ctx: ctx.obs.enemy.forced),
    "i_am_rooted": Sensor("bool", "You are rooted (no walking or dashing).", {}, lambda ctx: ctx.obs.me.rooted > 0.0),
    # Reading the enemy
    "enemy_ready": Sensor("bool", "The enemy could use this right now (their Dash is up, they hold an item, ...).",
                          {"ability": lambda cfg: ABILITY_CHOICES}, lambda ctx, ability: _enemy_ready(ctx, ability)),
    "enemy_cooldown": Sensor("number", "Seconds until the enemy can use this again (0 if ready).",
                             {"ability": lambda cfg: COOLDOWN_CHOICES},
                             lambda ctx, ability: ctx.obs.enemy.cooldowns[ability]),
    "since_enemy_used": Sensor("number", f"Seconds since the enemy last used this ({NEVER:g} if never).",
                               {"ability": lambda cfg: ABILITY_CHOICES},
                               lambda ctx, ability: ctx.since(ctx.memory.used["enemy"].get(ability))),
    # Memory
    "since_i_used": Sensor("number", f"Seconds since you last used this ({NEVER:g} if never).",
                           {"ability": lambda cfg: ABILITY_CHOICES},
                           lambda ctx, ability: ctx.since(ctx.memory.used["me"].get(ability))),
    "since_i_was_hit": Sensor("number", f"Seconds since you last lost HP ({NEVER:g} if never).", {},
                              lambda ctx: ctx.since(ctx.memory.was_hit)),
    "since_i_hit_enemy": Sensor("number", f"Seconds since the enemy last lost HP ({NEVER:g} if never).", {},
                                lambda ctx: ctx.since(ctx.memory.hit_enemy)),
    "in_mode": Sensor("bool", "Your bot is in this mode (every bot starts in normal).", {"mode": lambda cfg: MODES},
                      lambda ctx, mode: ctx.memory.mode == mode),
    "time_in_mode": Sensor("number", "Seconds since your bot last switched mode.", {},
                           lambda ctx: ctx.since(ctx.memory.mode_since)),
    "chance": Sensor("percent", "Randomly true this often, rolled fresh each decision. Combine with set mode for "
                     "choices that stick.", {}, lambda ctx, value: ctx.bot.rng.random() * 100.0 < value),
}


# ---- actions -----------------------------------------------------------------


@dataclass(frozen=True)
class ActionDef:
    channel: str  # "move", "ability" or "mode"
    help: str
    params: dict[str, Callable[[GameConfig], tuple[str, ...]]]
    run: Callable[..., object]  # returns Vec2 / Cast, KEEP, or None (can't, fall through)
    can_fail: bool = False  # True if it can return None (then the next rule in the channel gets the turn)


def _away_from(ctx: Context, frm: Vec2, step: float = STEP) -> Vec2:
    me = ctx.obs.me.pos
    dx, dy = me.x - frm.x, me.y - frm.y
    d = math.hypot(dx, dy) or 1.0
    return clamp_to_arena(Vec2(me.x + dx / d * step, me.y + dy / d * step), ctx.config)


def _strafe(ctx: Context) -> Vec2:
    if ctx.threat is not None:
        _, proj, offset = ctx.threat
        return dodge_target(ctx.obs, ctx.config, proj, offset)
    # No threat: circle the enemy, sideways to the line between us.
    me, en = ctx.obs.me.pos, ctx.obs.enemy.pos
    fake = ProjectileView(en, Vec2(me.x - en.x, me.y - en.y), is_own=False, ability_id="bolt")
    return dodge_target(ctx.obs, ctx.config, fake, 1.0)


def _hold(ctx: Context) -> object:
    # Stop once; re-sending a (possibly delayed) own position every decision drags us back.
    return KEEP if ctx.bot.holding_still else ctx.obs.me.pos


def _wander(ctx: Context) -> object:
    rng = ctx.bot.rng
    if ctx.bot.wander_target is None or rng.random() < WANDER_CHANGE:
        cfg = ctx.config
        ctx.bot.wander_target = Vec2(float(rng.uniform(0, cfg.arena_width)), float(rng.uniform(0, cfg.arena_height)))
        return ctx.bot.wander_target
    return KEEP


def _set_mode(ctx: Context, mode: str) -> object:
    if ctx.memory.mode != mode:
        ctx.memory.mode = mode
        ctx.memory.mode_since = ctx.now
    return KEEP


def _shoot(ctx: Context, aim: str) -> Cast | None:
    if not _ready(ctx, "bolt"):
        return None
    return Cast("bolt", ctx.intercept("bolt") if aim == "lead" else ctx.obs.enemy.pos)


def _dash(ctx: Context, direction: str) -> Cast | None:
    if not _ready(ctx, "dash"):
        return None
    me = ctx.obs.me.pos
    if direction == "away_from_threat":
        if ctx.threat is None:
            return None
        target = _strafe(ctx)
    elif direction == "toward_enemy":
        target = ctx.obs.enemy.pos
    elif direction == "away_from_enemy":
        target = _away_from(ctx, ctx.obs.enemy.pos)
    else:
        target = ctx.nearest_pickup
        if target is None:
            return None
    if abs(target.x - me.x) + abs(target.y - me.y) < 1.0:
        return None
    return Cast("dash", target)


def _use_item(ctx: Context, aim: str) -> Cast | None:
    item = ctx.obs.me.item
    if not _ready(ctx, "item"):
        return None
    obs = ctx.obs
    if item in PROJECTILE_ITEMS:
        return Cast(item, ctx.intercept(item) if aim == "lead" else obs.enemy.pos)
    if item == "shield":
        return Cast("shield", obs.me.pos)
    if item == "wall":
        if ctx.threat is not None:
            return wall_block(obs, ctx.threat[1])
        fake = ProjectileView(obs.enemy.pos, Vec2(0.0, 0.0), is_own=False, ability_id="bolt")
        return wall_block(obs, fake)  # between us and the enemy
    if item == "blast":
        if aim == "direct":
            return Cast("blast", obs.enemy.pos)
        return blast_cast(obs, ctx.config) or Cast("blast", obs.enemy.pos)
    return Cast(item, obs.enemy.pos)


ACTIONS: dict[str, ActionDef] = {
    "approach": ActionDef("move", "Walk toward the enemy.", {}, lambda ctx: ctx.obs.enemy.pos),
    "retreat": ActionDef("move", "Walk away from the enemy.", {}, lambda ctx: _away_from(ctx, ctx.obs.enemy.pos)),
    "strafe": ActionDef("move", "Step sideways: out of an incoming projectile's path, or around the enemy.", {}, _strafe),
    "go_to_pickup": ActionDef("move", "Walk to the nearest pickup (doesn't match if there is none).", {},
                              lambda ctx: ctx.nearest_pickup, can_fail=True),
    "go_to_heal": ActionDef("move", "Walk to the center heal spot (works before it appears, too).", {},
                            lambda ctx: heal_spot(ctx.config)),
    "hold": ActionDef("move", "Stand still.", {}, _hold),
    "wander": ActionDef("move", "Walk to random points.", {}, _wander),
    "shoot": ActionDef("ability", "Fire Bolt at the enemy, leading their movement or straight at them.",
                       {"aim": lambda cfg: AIM_CHOICES}, _shoot, can_fail=True),
    "dash": ActionDef("ability", "Dash in a direction.", {"direction": lambda cfg: DASH_CHOICES}, _dash, can_fail=True),
    "use_item": ActionDef("ability", "Use the held pickup, aimed sensibly for what it is.",
                          {"aim": lambda cfg: AIM_CHOICES}, _use_item, can_fail=True),
    "hold_fire": ActionDef("ability", "Cast nothing (stops lower ability rules).", {}, lambda ctx: KEEP),
    "set_mode": ActionDef("mode", "Switch your bot's mode. Takes effect right away for the rules below.",
                          {"mode": lambda cfg: MODES}, lambda ctx, mode: _set_mode(ctx, mode)),
}


# ---- validation ----------------------------------------------------------------


class RuleError(ValueError):
    """A bot file that doesn't follow the rule language. `.errors` lists every problem."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _check_params(where: str, given: dict, allowed: dict, config: GameConfig, errors: list[str], ignore: set[str]) -> None:
    for key, choices in allowed.items():
        if key not in given:
            errors.append(f"{where}: missing '{key}' (one of {', '.join(choices(config))})")
        elif given[key] not in choices(config):
            errors.append(f"{where}: '{key}' must be one of {', '.join(choices(config))}, not {given[key]!r}")
    for key in given:
        if key not in allowed and key not in ignore:
            errors.append(f"{where}: unexpected '{key}'")


def _check_condition(cond, where: str, config: GameConfig, errors: list[str], depth: int = 0) -> None:
    if not isinstance(cond, dict):
        errors.append(f"{where}: a condition must be an object")
        return
    if "not" in cond:
        if depth >= MAX_DEPTH:
            errors.append(f"{where}: 'not' nested too deeply")
        elif len(cond) != 1:
            errors.append(f"{where}: 'not' can't have other keys")
        else:
            _check_condition(cond["not"], f"{where}.not", config, errors, depth + 1)
        return
    name = cond.get("sensor")
    if name not in SENSORS:
        errors.append(f"{where}: unknown sensor {name!r}")
        return
    sensor = SENSORS[name]
    if sensor.kind == "percent":
        value = cond.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            errors.append(f"{where}: '{name}' needs a 'value' from 0 to 100")
        _check_params(where, cond, sensor.params, config, errors, {"sensor", "value"})
    elif sensor.kind == "number":
        if cond.get("op") not in ("<", ">"):
            errors.append(f"{where}: number sensor '{name}' needs 'op' of '<' or '>'")
        value = cond.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append(f"{where}: number sensor '{name}' needs a numeric 'value'")
        _check_params(where, cond, sensor.params, config, errors, {"sensor", "op", "value"})
    else:
        _check_params(where, cond, sensor.params, config, errors, {"sensor"})


def validate(spec, config: GameConfig = DEFAULT_CONFIG) -> list[str]:
    """Every problem with a bot spec, as readable messages (empty if it's valid)."""
    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["a bot must be an object with 'name' and 'rules'"]
    if spec.get("version", VERSION) != VERSION:
        errors.append(f"unsupported version {spec.get('version')!r} (expected {VERSION})")
    if not isinstance(spec.get("name", ""), str):
        errors.append("'name' must be text")
    rules = spec.get("rules")
    if not isinstance(rules, list):
        return errors + ["'rules' must be a list"]
    if len(rules) > MAX_RULES:
        errors.append(f"too many rules ({len(rules)} > {MAX_RULES})")
    for i, rule in enumerate(rules, 1):
        where = f"rule {i}"
        if not isinstance(rule, dict) or "then" not in rule:
            errors.append(f"{where}: needs 'then' (and optionally 'if')")
            continue
        conds = rule.get("if", [])
        if not isinstance(conds, list):
            errors.append(f"{where}: 'if' must be a list of conditions")
        else:
            for j, cond in enumerate(conds, 1):
                _check_condition(cond, f"{where} condition {j}", config, errors)
        action = rule["then"]
        name = action.get("action") if isinstance(action, dict) else None
        if name not in ACTIONS:
            errors.append(f"{where}: unknown action {name!r}")
        else:
            _check_params(where, action, ACTIONS[name].params, config, errors, {"action"})
    return errors


# ---- explaining a bot ------------------------------------------------------------
#
# Static checks behind Build's "What your bot does" panel. A bot runs the first matching
# rule per channel, so an earlier rule that always acts whenever a later one would match
# makes the later one dead. Rule numbers are 1-based, as in the editor.

CHANNEL_NAMES = {"move": "moving", "ability": "abilities", "mode": "modes"}
MODE_SENSORS = ("in_mode", "time_in_mode")  # their truth can change after a set_mode earlier in the list


def _key(cond: dict) -> str:
    return json.dumps(cond, sort_keys=True)


def _contradiction(conds: list[dict]) -> str | None:
    """Why these conditions can never all hold at once, or None."""
    plain = {_key(c) for c in conds if "not" not in c}
    for c in conds:
        if "not" in c and _key(c["not"]) in plain:
            return f"it needs both \"if\" and \"unless\" {c['not']['sensor'].replace('_', ' ')}"
    bounds: dict[str, list] = {}  # sensor + params -> [low, low inclusive, high, high inclusive]
    for c in conds:
        neg = "not" in c
        base = c["not"] if neg else c
        if SENSORS.get(base.get("sensor")) is None or SENSORS[base["sensor"]].kind != "number":
            continue
        k = _key({x: v for x, v in base.items() if x not in ("op", "value")})
        b = bounds.setdefault(k, [-math.inf, False, math.inf, False])
        upper = (base["op"] == "<") != neg  # "x < v" or "unless x > v" bound x from above
        v, inclusive = base["value"], neg
        if upper and (v < b[2] or (v == b[2] and not inclusive)):
            b[2], b[3] = v, inclusive
        if not upper and (v > b[0] or (v == b[0] and not inclusive)):
            b[0], b[1] = v, inclusive
        if b[0] > b[2] or (b[0] == b[2] and not (b[1] and b[3])):
            return f"no value of {base['sensor'].replace('_', ' ')} fits all its limits"
    return None


def analyze(spec: dict) -> dict:
    """Rule numbers per channel in priority order, plus warnings about rules that can't matter.
    Each warning: {"kind", "rules": [numbers] (or [None]), "message"}; shadowing ones add "by"."""
    rules = spec.get("rules", [])
    channel = [ACTIONS[r["then"]["action"]].channel for r in rules]
    groups = {ch: [i + 1 for i, c in enumerate(channel) if c == ch] for ch in CHANNEL_NAMES}
    warnings: list[dict] = []
    conds = [r.get("if", []) for r in rules]
    keys = [{_key(c) for c in cs} for cs in conds]
    dead: set[int] = set()
    for i, rule in enumerate(rules):
        why = _contradiction(conds[i])
        if why:
            dead.add(i)
            warnings.append({"kind": "contradiction", "rules": [i + 1],
                             "message": f"Rule {i + 1} can never run: {why}."})
    for i, rule in enumerate(rules):
        act = ACTIONS[rule["then"]["action"]]
        if i in dead or act.can_fail or any(SENSORS[_base(c)["sensor"]].kind == "percent" for c in conds[i]):
            continue  # it may not act even when its conditions hold, so it hides nothing
        mode_dependent = any(_base(c)["sensor"] in MODE_SENSORS for c in conds[i])
        shadowed = []
        for j in range(i + 1, len(rules)):
            if channel[j] != channel[i] or j in dead or not keys[i] <= keys[j]:
                continue
            switch_between = any(channel[k] == "mode" for k in range(i + 1, j))
            if mode_dependent and switch_between:
                continue  # the mode can change between the two rules
            shadowed.append(j)
        if shadowed:
            dead.update(shadowed)
            many = len(shadowed) > 1
            names = ", ".join(str(j + 1) for j in shadowed)
            them = "them" if many else "it"
            cause = "always matches first" if not conds[i] else f"matches whenever {'they' if many else 'it'} would"
            warnings.append({"kind": "shadowed", "rules": [j + 1 for j in shadowed], "by": i + 1,
                             "message": f"Rule{'s' if many else ''} {names} never run{'' if many else 's'}: rule {i + 1}, "
                                        f"above {them} in {CHANNEL_NAMES[channel[i]].capitalize()}, {cause}."})
    if not groups["move"]:
        warnings.append({"kind": "no_move", "rules": [None], "message": "Your bot has no move rules, so it never moves."})
    if not groups["ability"]:
        warnings.append({"kind": "no_ability", "rules": [None],
                         "message": "Your bot has no ability rules, so it never shoots or dashes."})
    return {"groups": groups, "warnings": warnings}


def _base(cond: dict) -> dict:
    return cond["not"] if "not" in cond else cond


# ---- the bot -------------------------------------------------------------------


class RuleBot:
    def __init__(self, spec: dict, config: GameConfig = DEFAULT_CONFIG) -> None:
        errors = validate(spec, config)
        if errors:
            raise RuleError(errors)
        self.spec = spec
        self.name = spec.get("name", "rule bot")
        self.config = config
        self.rules = [(rule.get("if", []), rule["then"]) for rule in spec["rules"]]
        self.rng = np.random.default_rng(0)
        self.reset(self.rng)

    def reset(self, rng: np.random.Generator) -> None:
        self.rng = rng
        self.holding_still = False
        self.wander_target: Vec2 | None = None
        self.memory = Memory()
        self.trace: dict = {"status": [UNREACHED] * len(self.rules), "fired": {}, "mode": MODES[0]}

    def _holds(self, cond: dict, ctx: Context) -> bool:
        if "not" in cond:
            return not self._holds(cond["not"], ctx)
        sensor = SENSORS[cond["sensor"]]
        if sensor.kind == "percent":
            return sensor.read(ctx, cond["value"])
        args = [cond[key] for key in sensor.params]
        value = sensor.read(ctx, *args)
        if sensor.kind == "number":
            return value < cond["value"] if cond["op"] == "<" else value > cond["value"]
        return bool(value)

    def act(self, obs: Observation) -> Action:
        self.memory.update(obs, self.config)
        ctx = Context(obs, self.config, self)
        move = cast = None
        done = {channel: False for channel in CHANNELS}
        moved_by = None
        status = [UNREACHED] * len(self.rules)
        fired: dict[str, int] = {}
        for i, (conds, action) in enumerate(self.rules):
            ad = ACTIONS[action["action"]]
            if done[ad.channel]:
                status[i] = SKIPPED
                continue
            if not all(self._holds(c, ctx) for c in conds):
                status[i] = FALSE
                continue
            result = ad.run(ctx, *[action[key] for key in ad.params])
            if result is None:
                status[i] = COULDNT
                continue  # can't do it right now: let a later rule try
            status[i] = FIRED
            fired[ad.channel] = i
            done[ad.channel] = True
            if ad.channel == "move":
                moved_by = action["action"]
                move = None if result is KEEP else result
            elif ad.channel == "ability":
                cast = None if result is KEEP else result
            if done["move"] and done["ability"] and done["mode"]:
                break
        self.holding_still = moved_by == "hold"
        self.trace = {"status": status, "fired": fired, "mode": self.memory.mode}
        if move is None and cast is None:
            return NOOP
        return Action(move=move, cast=cast)


def load_rule_bot(path: str | pathlib.Path, config: GameConfig = DEFAULT_CONFIG) -> RuleBot:
    with open(path) as f:
        try:
            spec = json.load(f)
        except json.JSONDecodeError as exc:
            raise RuleError([f"not valid JSON: {exc}"]) from exc
    return RuleBot(spec, config)


def vocabulary(config: GameConfig = DEFAULT_CONFIG) -> dict:
    """Every sensor and action with its parameters, for building editor blocks."""
    def params(defs):
        return {key: list(choices(config)) for key, choices in defs.items()}
    return {
        "version": VERSION,
        "sensors": {n: {"kind": s.kind, "help": s.help, "params": params(s.params)} for n, s in SENSORS.items()},
        "actions": {n: {"channel": a.channel, "help": a.help, "params": params(a.params)} for n, a in ACTIONS.items()},
    }


def main(argv: list[str] | None = None) -> None:
    """python -m arena.bots.rules check bots/*.json   |   python -m arena.bots.rules vocab"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Check rule-bot files or print the block vocabulary.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("check", help="validate bot files")
    check.add_argument("files", nargs="+")
    sub.add_parser("vocab", help="print sensors and actions as JSON")
    args = parser.parse_args(argv)
    if args.cmd == "vocab":
        print(json.dumps(vocabulary(), indent=2))
        return
    bad = 0
    for path in args.files:
        try:
            load_rule_bot(path)
            print(f"ok      {path}")
        except (RuleError, OSError) as exc:
            bad += 1
            errors = exc.errors if isinstance(exc, RuleError) else [str(exc)]
            print(f"invalid {path}")
            for err in errors:
                print(f"        - {err}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
