"""Bot registry. Each bot lives in its own file and takes the game config.

Trained policies are bots too: a name that isn't a scripted bot resolves to
models/<name>.zip, or to the given path if it ends in .zip. A path ending in
.json is a rule-list bot (see arena/bots/rules.py), e.g. one from the editor.
"""

import pathlib
from collections.abc import Callable

from arena.config import DEFAULT_CONFIG, GameConfig
from arena.controller import Controller
from arena.bots.aimer import AimerBot
from arena.bots.dodger import DodgerBot
from arena.bots.idle import IdleBot
from arena.bots.leader import LeaderBot
from arena.bots.random_bot import RandomBot

BOTS: dict[str, Callable[[GameConfig], Controller]] = {
    "idle": IdleBot,
    "random": RandomBot,
    "aimer": AimerBot,
    "leader": LeaderBot,
    "dodger": DodgerBot,
}


MODELS_DIR = pathlib.Path("models")  # your own training runs (not committed)
POLICIES_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "policies"  # the shipped trained bots


def policy_path(name: str) -> pathlib.Path | None:
    """A trained policy file for this name: a .zip/.npz path, or models/<name>.zip, models/<name>.npz, else policies/<name>.npz."""
    if name.endswith((".zip", ".npz")):
        path = pathlib.Path(name)
        return path if path.is_file() else None
    for path in (MODELS_DIR / f"{name}.zip", MODELS_DIR / f"{name}.npz", POLICIES_DIR / f"{name}.npz"):
        if path.is_file():
            return path
    return None


def available_bots() -> list[str]:
    trained = {p.stem for d, pattern in ((MODELS_DIR, "*.zip"), (MODELS_DIR, "*.npz"), (POLICIES_DIR, "*.npz"))
               if d.is_dir() for p in d.glob(pattern)}
    trained = sorted(trained)
    return sorted(BOTS) + trained


def make_bot(name: str, config: GameConfig = DEFAULT_CONFIG) -> Controller:
    if name in BOTS:
        return BOTS[name](config)
    if name.endswith(".json"):
        from arena.bots.rules import load_rule_bot

        return load_rule_bot(name, config)
    path = policy_path(name)
    if path is None:
        raise ValueError(f"unknown bot {name!r}; known: {', '.join(available_bots())}")
    if path.suffix == ".npz":
        from arena.bots.numpy_policy import NumpyPolicyBot

        return NumpyPolicyBot(path, config)
    from arena.bots.policy import PolicyBot  # needs the [rl] extras

    return PolicyBot(path, config)
