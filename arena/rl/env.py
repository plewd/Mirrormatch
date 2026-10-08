"""Gymnasium env: one learning agent vs. an opponent drawn from a pool.

The agent is held to the same fairness rules as every bot in eval: it decides
once every `rate_limit` ticks from an observation `reaction_delay` ticks old,
and its aim gets the preset's noise. This mirrors FairController exactly, so a
trained policy behaves the same in training, eval, and play.
"""

import gymnasium as gym
import numpy as np

from arena.bots import make_bot
from arena.config import DEFAULT_CONFIG, DIFFICULTIES, Difficulty, GameConfig
from arena.fairness import DelayBuffer, FairController, add_aim_noise
from arena.match import controller_rng
from arena.rl.features import ENCODERS
from arena.sim.game import Game
from arena.sim.spawns import mirrored_random_spawns, spawn_rng
from arena.sim.types import NOOP

DEFAULT_POOL = ("random", "aimer", "leader", "dodger")


class MirrormatchEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        opponents: tuple[str, ...] | list[str] = DEFAULT_POOL,
        difficulty: str | Difficulty = "normal",
        config: GameConfig = DEFAULT_CONFIG,
        hit_reward: float = 0.2,
        encoder: str = "v3",
    ) -> None:
        self.config = config
        self.preset = DIFFICULTIES[difficulty] if isinstance(difficulty, str) else difficulty
        self.encoder = ENCODERS[encoder](config)
        self.hit_reward = hit_reward
        self.pool = list(opponents)
        self.observation_space = gym.spaces.Box(-5.0, 5.0, shape=(self.encoder.obs_size,), dtype=np.float32)
        self.action_space = gym.spaces.MultiDiscrete(self.encoder.action_nvec)

    def set_opponents(self, opponents: list[str]) -> None:
        """Replace the opponent pool; takes effect at the next reset."""
        self.pool = list(opponents)

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        cfg = self.config
        self.game_seed = game_seed = int(self.np_random.integers(2**31))
        self.side = int(self.np_random.integers(2))
        self.opponent_name = self.pool[int(self.np_random.integers(len(self.pool)))]
        self.game = Game(cfg, game_seed, mirrored_random_spawns(cfg, spawn_rng(game_seed)))
        self.opponent = FairController(make_bot(self.opponent_name, cfg), self.preset)
        self.opponent.reset(controller_rng(game_seed, 1 - self.side))
        self.agent_rng = controller_rng(game_seed, self.side)
        self.delay = DelayBuffer(self.preset.reaction_delay)
        self.seen = self.delay.push(self.game.observe(self.side))
        return self.encoder.encode(self.seen), {}

    def step(self, action):
        game, side = self.game, self.side
        state = game.state
        me, enemy = state.champions[side], state.champions[1 - side]
        hp_me, hp_enemy = me.hp, enemy.hp

        agent_action = self.encoder.decode(action, self.seen)
        agent_action = add_aim_noise(agent_action, self.seen.me.pos, self.preset.aim_noise_deg, self.agent_rng)
        for k in range(self.preset.rate_limit):
            if k > 0:
                self.delay.push(game.observe(side))  # the agent "sees" every tick, decides on the first
            a_me = agent_action if k == 0 else NOOP
            a_opp = self.opponent.act(game.observe(1 - side))
            if side == 0:
                game.step(a_me, a_opp)
            else:
                game.step(a_opp, a_me)
            if state.done:
                break

        reward = self.hit_reward * ((hp_enemy - enemy.hp) - (hp_me - me.hp))
        info = {}
        if state.done:
            if state.winner is not None:
                reward += 1.0 if state.winner == side else -1.0
            info = {"winner": None if state.winner is None else int(state.winner == side), "opponent": self.opponent_name}
        else:
            self.seen = self.delay.push(game.observe(side))
        return self.encoder.encode(self.seen), float(reward), state.done, False, info
