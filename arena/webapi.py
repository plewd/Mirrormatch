"""The Python side of the browser front end (runs inside Pyodide).

JavaScript drives a Session at the sim's tick rate and draws the snapshots it
returns. Everything crosses the boundary as JSON text, so the JS side needs no
knowledge of Python objects. The renderer only reads snapshots; it never changes
the sim.
"""

import copy
import dataclasses
import json
import pathlib

from arena.bots import make_bot
from arena.bots.common import incoming_threat
from arena.bots.rules import RuleBot, RuleError, analyze, validate
from arena.config import DEFAULT_CONFIG, DIFFICULTIES
from arena.controller import Controller
from arena.fairness import FairController
from arena.human import HumanController
from arena.match import controller_rng, run_match
from arena.sim.game import Game
from arena.sim.spawns import mirrored_random_spawns, spawn_rng
from arena.sim.types import NOOP, Observation, Vec2

HUMAN = "human"
CONFIG = DEFAULT_CONFIG
BUILTIN_BOTS = ("idle", "random", "aimer", "leader", "dodger")
# Exported policies: bundled next to the package in the browser; models/ when run from the repo.
POLICY_DIRS = (pathlib.Path(__file__).resolve().parent.parent / "policies", pathlib.Path("models"))


def policies() -> dict[str, pathlib.Path]:
    found: dict[str, pathlib.Path] = {}
    for d in POLICY_DIRS:
        if d.is_dir():
            for path in sorted(d.glob("*.npz")):
                found.setdefault(path.stem, path)
    return found


def make_controller(spec: str) -> Controller:
    """A bot from a built-in name, an exported policy name, or rule-bot JSON text."""
    text = spec.strip()
    if text.startswith("{"):
        return RuleBot(json.loads(text), CONFIG)
    trained = policies().get(text)
    if trained is not None:
        from arena.bots.numpy_policy import NumpyPolicyBot

        return NumpyPolicyBot(trained, CONFIG)
    return make_bot(text, CONFIG)


def check_bot(spec_json: str) -> str:
    """Validate rule-bot JSON text: returns a JSON list of error messages."""
    try:
        spec = json.loads(spec_json)
    except json.JSONDecodeError as exc:
        return json.dumps([f"not valid JSON: {exc}"])
    return json.dumps(validate(spec, CONFIG))


def analyze_bot(spec_json: str) -> str:
    """'Explain my bot': rule groups and warnings (JSON), or {"error": ...} for an invalid spec."""
    spec = json.loads(spec_json)
    errors = validate(spec, CONFIG)
    return json.dumps({"error": errors[0]} if errors else analyze(spec))


REPLAY_VERSION = 1
CENTER_RADIUS = 150.0  # "near the center" for the time-in-center stat


def new_stats() -> dict:
    """Per-player match statistics, built from the engine's event log."""
    return {"casts": {}, "hits": {}, "dealt": {}, "taken": {}, "blocks": 0, "pickups": 0,
            "items_used": 0, "heals": 0, "healed": 0, "center_ticks": 0, "distance": 0.0}


def tally(stats: list[dict], game: Game) -> None:
    """Fold one tick's events (and positions) into both players' stats."""
    loadout = game.params.loadout
    for ev in game.state.events:
        kind = ev[0]
        if kind == "cast":
            _, player, ability = ev
            st = stats[player]
            st["casts"][ability] = st["casts"].get(ability, 0) + 1
            if ability not in loadout:
                st["items_used"] += 1
        elif kind == "hit":
            _, source, _target, ability = ev
            stats[source]["hits"][ability] = stats[source]["hits"].get(ability, 0) + 1
        elif kind == "damage":
            _, source, target, ability, amount = ev
            if source >= 0:
                stats[source]["dealt"][ability] = stats[source]["dealt"].get(ability, 0) + amount
            stats[target]["taken"][ability] = stats[target]["taken"].get(ability, 0) + amount
        elif kind == "blocked":
            stats[ev[1]]["blocks"] += 1
        elif kind == "pickup":
            stats[ev[1]]["pickups"] += 1
        elif kind == "heal":
            stats[ev[1]]["heals"] += 1
            stats[ev[1]]["healed"] += ev[2]
    cx, cy = game.params.width / 2, game.params.height / 2
    for st, champ in zip(stats, game.state.champions):
        st["distance"] += (champ.vx * champ.vx + champ.vy * champ.vy) ** 0.5
        if (champ.x - cx) ** 2 + (champ.y - cy) ** 2 <= CENTER_RADIUS ** 2:
            st["center_ticks"] += 1
def bot_view(seen: Observation, player: int, now_tick: int, game: Game) -> dict:
    """What a bot saw when it last decided, in world coordinates (its view is mirrored
    on the right side): its position, the enemy's, the enemy projectiles, and which of
    them it reads as the incoming threat. `age` is how stale that view is now."""
    rate = game.params.tick_rate
    w = game.params.width

    def world(v: Vec2) -> list[float]:
        return [w - v.x if player == 1 else v.x, v.y]

    shots = [pr for pr in seen.projectiles if not pr.is_own]
    threat = incoming_threat(seen, CONFIG)
    tick = round(game.params.time_limit_ticks - seen.time_remaining * rate)
    return {
        "tick": tick, "age": (now_tick - tick) / rate,
        "me": world(seen.me.pos), "enemy": world(seen.enemy.pos),
        "projectiles": [{"x": world(pr.pos)[0], "y": pr.pos.y, "r": CONFIG.abilities[pr.ability_id].radius,
                         "ability": pr.ability_id} for pr in shots],
        "threat": None if threat is None else next(k for k, pr in enumerate(shots) if pr is threat[1]),
    }


CHECKPOINT_EVERY = 150  # ticks (5 s) between timeline checkpoints, so a seek re-simulates at most this many


class Session:
    """One match. Either side is HUMAN or a bot spec; bots get the difficulty preset.

    Human commands are logged with the tick they were issued on, so a match can be
    saved as a tiny replay (seed + bots + commands) and re-simulated exactly."""

    def __init__(self, left: str, right: str, difficulty: str = "normal", seed: int = 0) -> None:
        self.seed = seed
        self.specs = (left, right)
        self.difficulty = difficulty
        self.log: list[list] = []  # [tick, command dict] for every human command
        self.scripted: dict[int, list[dict]] = {}  # tick -> commands to replay
        self.checkpoints: dict[int, object] = {}  # tick -> frozen copy of the live parts, for seeking
        self.stats = [new_stats(), new_stats()]
        self.recent: list[list] = []  # engine events since the last snapshot, for sound and effects
        self.game = Game(CONFIG, seed, mirrored_random_spawns(CONFIG, spawn_rng(seed)))
        self.controllers: list[Controller] = []
        self.human: HumanController | None = None
        for player, spec in enumerate((left, right)):
            if spec == HUMAN:
                if player != 0:
                    raise ValueError("the human plays the left side")
                self.human = HumanController()
                ctrl: Controller = self.human
            else:
                ctrl = FairController(make_controller(spec), DIFFICULTIES[difficulty])
            ctrl.reset(controller_rng(seed, player))
            self.controllers.append(ctrl)

    def command(self, cmd_json: str) -> None:
        """A human command in world coordinates: {"move": [x, y]} and/or {"cast": "bolt"|"dash"|"item", "aim": [x, y]}."""
        if self.human is None:
            return
        self._apply(json.loads(cmd_json))

    def _apply(self, cmd: dict) -> None:
        self.log.append([self.game.state.tick, cmd])
        if cmd.get("move"):
            self.human.command_move(Vec2(*cmd["move"]))
        cast = cmd.get("cast")
        if cast:
            aid = self.game.state.champions[0].item if cast == "item" else cast
            if aid and not self.game.state.done:
                self.human.command_cast(aid, Vec2(*cmd["aim"]))

    def advance(self, ticks: int) -> str:
        """Step up to `ticks` ticks (stopping at game end) and return a snapshot."""
        game = self.game
        for _ in range(ticks):
            if game.state.done:
                break
            if game.state.tick % CHECKPOINT_EVERY == 0 and game.state.tick not in self.checkpoints:
                self.checkpoints[game.state.tick] = self._freeze()
            for cmd in self.scripted.pop(game.state.tick, ()):
                self._apply(cmd)
            a0 = self.controllers[0].act(game.observe(0))
            a1 = self.controllers[1].act(game.observe(1))
            game.step(a0, a1)
            tally(self.stats, game)
            self.recent.extend([*ev, game.state.tick] for ev in game.state.events)
        return self.snapshot()

    # ---- timeline ----------------------------------------------------------------

    def _freeze(self) -> object:
        """A deep copy of everything that changes during a match (one copy keeps
        shared references, like the human controller in the list, consistent)."""
        return copy.deepcopy((self.game, self.controllers, self.human, self.scripted, self.log, self.stats))

    def _thaw(self, frozen: object) -> None:
        self.game, self.controllers, self.human, self.scripted, self.log, self.stats = copy.deepcopy(frozen)

    def prepare_timeline(self) -> int:
        """Play a copy of this match to the end, keeping checkpoints along the way.
        Returns the match length in ticks. Only for matches without live human input."""
        if self.human is not None and not self.scripted:
            raise ValueError("a live human match has no known end")
        here = self._freeze()
        self.advance(10**9)
        length = self.game.state.tick
        self._thaw(here)
        self.recent = []  # the look-ahead run's events aren't "new"
        return length

    def seek(self, tick: int) -> str:
        """Jump to `tick` (exact: resumes from the nearest checkpoint and re-simulates)."""
        tick = max(0, tick)
        current = self.game.state.tick
        if not (current <= tick and tick - current <= CHECKPOINT_EVERY):
            start = max((t for t in self.checkpoints if t <= tick), default=None)
            if start is not None and not (current <= tick and current > start):
                self._thaw(self.checkpoints[start])
        self.advance(tick - self.game.state.tick)
        self.recent = []  # a jump shouldn't replay the sounds of everything skipped over
        return self.snapshot()

    def replay(self, left_label: str = "", right_label: str = "") -> str:
        """The match so far as a self-contained replay file (JSON text)."""
        return json.dumps({
            "mirrormatch_replay": REPLAY_VERSION, "seed": self.seed, "difficulty": self.difficulty,
            "left": {"spec": self.specs[0], "label": left_label or self.specs[0][:40]},
            "right": {"spec": self.specs[1], "label": right_label or self.specs[1][:40]},
            "commands": self.log,
        })

    @staticmethod
    def from_replay(replay_json: str) -> "Session":
        """A fresh session that will re-enact a saved match tick for tick."""
        rep = json.loads(replay_json)
        if rep.get("mirrormatch_replay") != REPLAY_VERSION:
            raise ValueError("not a Mirrormatch replay file (or an unsupported version)")
        session = Session(rep["left"]["spec"], rep["right"]["spec"], rep["difficulty"], rep["seed"])
        for tick, cmd in rep["commands"]:
            session.scripted.setdefault(int(tick), []).append(cmd)
        return session

    def debug(self) -> list[dict | None]:
        """What each bot decided most recently, for the decision debugger.

        Rule bots report their trace (which rule fired per channel, every rule's
        status, current mode). Other bots report the last action they returned."""
        out: list[dict | None] = []
        for player, ctrl in enumerate(self.controllers):
            inner = getattr(ctrl, "inner", None)  # FairController wraps the real bot
            if inner is None:
                out.append(None)  # the human
                continue
            if isinstance(inner, RuleBot):
                fired = inner.trace["fired"]
                entry = {
                    "kind": "rules", "status": inner.trace["status"], "mode": inner.trace["mode"],
                    "fired": {ch: {"index": i, "action": inner.rules[i][1]["action"]} for ch, i in fired.items()},
                }
            else:
                last = ctrl.last_action
                entry = {"kind": "other", "cast": last.cast.ability_id if last.cast else None, "moving": bool(last.move)}
            seen = ctrl.last_seen
            entry["seen"] = None if seen is None else bot_view(seen, player, self.game.state.tick, self.game)
            out.append(entry)
        return out

    def snapshot(self) -> str:
        s = self.game.state
        p = self.game.params
        rate = p.tick_rate

        def champ(c):
            cast = None
            if c.cast is not None:
                total = max(1, p.abilities[c.cast.ability_id].cast_ticks)
                cast = {"ability": c.cast.ability_id, "progress": 1.0 - c.cast.ticks_remaining / total,
                        "dir": [c.cast.dir_x, c.cast.dir_y]}
            return {
                "x": c.x, "y": c.y, "vx": c.vx, "vy": c.vy, "hp": c.hp, "cast": cast,
                "forced": c.forced is not None, "rooted": c.root_ticks > 0, "shielded": c.shield_ticks > 0,
                "item": c.item,
                "cooldowns": {aid: {"left": t / rate, "frac": t / max(1, p.abilities[aid].cooldown_ticks)}
                              for aid, t in c.cooldowns.items()},
            }

        return json.dumps({
            "tick": s.tick,
            "time_left": max(0, p.time_limit_ticks - s.tick) / rate,
            "done": s.done,
            "winner": s.winner,
            "champions": [champ(c) for c in s.champions],
            "projectiles": [{"id": pr.pid, "x": pr.x, "y": pr.y, "dx": pr.dir_x, "dy": pr.dir_y, "r": pr.radius,
                             "owner": pr.owner, "ability": pr.ability_id,
                             "trail": min(pr.traveled, 3 * pr.speed)} for pr in s.projectiles],
            "walls": [{"ax": w.ax, "ay": w.ay, "bx": w.bx, "by": w.by, "owner": w.owner} for w in s.walls],
            "zones": [{"x": z.x, "y": z.y, "r": z.radius, "owner": z.owner,
                       "frac": 1.0 - z.ticks_remaining / max(1, p.abilities[z.ability_id].duration_ticks)}
                      for z in s.zones],
            "pickups": [{"x": pk.x, "y": pk.y, "ability": pk.ability_id} for pk in s.pickups],
            "heal": {"up": s.heal_up, "x": p.width / 2, "y": p.height / 2, "r": p.heal_radius,
                     "in": 0.0 if s.heal_up else max(0, s.next_heal_tick - s.tick) / rate},
            "debug": self.debug(),
            "stats": self.stats if s.done else None,
            "events": self._take_recent(),
        })

    def _take_recent(self) -> list[list]:
        events, self.recent = self.recent, []
        return events


def arena_info() -> str:
    """Static numbers the renderer needs."""
    p = DEFAULT_CONFIG
    return json.dumps({
        "width": p.arena_width, "height": p.arena_height, "tick_rate": p.tick_rate,
        "champion_radius": p.champion_radius, "champion_hp": p.champion_hp, "pickup_radius": p.pickup_radius,
        "loadout": list(p.loadout), "difficulties": list(DIFFICULTIES),
        "pickup_pool": list(p.pickup_pool), "time_limit": p.time_limit, "champion_speed": p.champion_speed,
        "abilities": {aid: dataclasses.asdict(st) for aid, st in p.abilities.items()},
        "difficulty_presets": {name: dataclasses.asdict(d) for name, d in DIFFICULTIES.items()},
        "pickup_first_spawn": p.pickup_first_spawn, "pickup_interval": p.pickup_interval, "pickup_max": p.pickup_max,
        "heal_first_spawn": p.heal_first_spawn, "heal_respawn": p.heal_respawn, "heal_amount": p.heal_amount,
        "builtin_bots": list(BUILTIN_BOTS) + sorted(policies()),
        "trained_bots": sorted(policies()),
    })


def play_game(left: str, right: str, seed: int, left_first: bool = True, difficulty: str = "normal") -> str:
    """One headless game: "win", "loss" or "draw" from `left`'s point of view. The
    editor calls this game by game so the page stays responsive."""
    preset = DIFFICULTIES[difficulty]
    a = FairController(make_controller(left), preset)
    b = FairController(make_controller(right), preset)
    p0, p1 = (a, b) if left_first else (b, a)
    res = run_match(p0, p1, CONFIG, seed, mirrored_random_spawns(CONFIG, spawn_rng(seed)))
    if res.winner is None:
        return "draw"
    return "win" if (res.winner == 0) == left_first else "loss"


def run_series(left: str, right: str, games: int, seed: int = 0, difficulty: str = "normal") -> str:
    """Headless games between two bot specs, alternating sides: JSON {wins, losses, draws} for `left`."""
    wins = losses = draws = 0
    preset = DIFFICULTIES[difficulty]
    for g in range(games):
        game_seed = seed + g
        a = FairController(make_controller(left), preset)
        b = FairController(make_controller(right), preset)
        left_first = g % 2 == 0
        p0, p1 = (a, b) if left_first else (b, a)
        res = run_match(p0, p1, CONFIG, game_seed, mirrored_random_spawns(CONFIG, spawn_rng(game_seed)))
        if res.winner is None:
            draws += 1
        elif (res.winner == 0) == left_first:
            wins += 1
        else:
            losses += 1
    return json.dumps({"wins": wins, "losses": losses, "draws": draws})


__all__ = ["Session", "HUMAN", "arena_info", "check_bot", "play_game", "run_series", "RuleError", "NOOP"]
