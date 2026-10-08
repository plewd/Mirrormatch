"""A trained policy (stable-baselines3 .zip) as a normal bot.

Load with make_bot("<name>") for models/<name>.zip, or make_bot("path/to/model.zip").
The policy decides on every call; the FairController wrapper provides the same
rate limit, delay, and aim noise it was trained under.
"""

import pathlib

import numpy as np

from arena.config import DEFAULT_CONFIG, GameConfig
from arena.rl.features import encoder_for_obs_size
from arena.sim.types import Action, Observation

_MODELS: dict[str, object] = {}


def load_model(path: pathlib.Path):
    """Load once per process. Paths are cached, so save checkpoints under new names."""
    key = str(path.resolve())
    if key not in _MODELS:
        import torch
        from stable_baselines3 import PPO

        torch.set_num_threads(1)  # many games run in parallel processes; don't oversubscribe
        _MODELS[key] = PPO.load(key, device="cpu")
    return _MODELS[key]


class PolicyBot:
    def __init__(self, path: pathlib.Path, config: GameConfig = DEFAULT_CONFIG) -> None:
        self.model = load_model(pathlib.Path(path))
        self.encoder = encoder_for_obs_size(self.model.observation_space.shape[0], config)

    def reset(self, rng: np.random.Generator) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        action, _ = self.model.predict(self.encoder.encode(obs), deterministic=True)
        return self.encoder.decode(action, obs)
