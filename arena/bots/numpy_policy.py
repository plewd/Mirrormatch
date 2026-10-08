"""A trained policy as a bot without PyTorch: its exported weights (.npz) run in numpy.

Export with `python -m arena.rl.export <name>` (writes models/<name>.npz). This is
what runs trained bots in the browser, and it is also faster than torch for one
observation at a time.
"""

import pathlib

import numpy as np

from arena.config import DEFAULT_CONFIG, GameConfig
from arena.rl.features import encoder_for_obs_size
from arena.sim.types import Action, Observation

_WEIGHTS: dict[str, dict[str, np.ndarray]] = {}


def load_weights(path: pathlib.Path) -> dict[str, np.ndarray]:
    key = str(path.resolve())
    if key not in _WEIGHTS:
        with np.load(path) as data:
            _WEIGHTS[key] = {k: data[k] for k in data.files}
    return _WEIGHTS[key]


class NumpyPolicyBot:
    def __init__(self, path: pathlib.Path, config: GameConfig = DEFAULT_CONFIG) -> None:
        w = load_weights(pathlib.Path(path))
        self.layers = [(w[f"w{i}"], w[f"b{i}"]) for i in range(int(w["hidden_layers"]))]
        self.wa, self.ba = w["wa"], w["ba"]
        self.splits = np.cumsum(w["nvec"])[:-1]
        self.encoder = encoder_for_obs_size(self.layers[0][0].shape[1], config)

    def reset(self, rng: np.random.Generator) -> None:
        pass

    def __deepcopy__(self, memo: dict) -> "NumpyPolicyBot":
        return self  # stateless between decisions, and the weights are read-only: share them

    def logits(self, features: np.ndarray) -> np.ndarray:
        h = features.astype(np.float32)
        for weight, bias in self.layers:
            h = np.tanh(weight @ h + bias)
        return self.wa @ h + self.ba

    def act(self, obs: Observation) -> Action:
        logits = self.logits(self.encoder.encode(obs))
        action = [int(np.argmax(part)) for part in np.split(logits, self.splits)]
        return self.encoder.decode(action, obs)
