"""Train a PPO policy: python -m arena.rl.train --name ppo_v1 --steps 5000000

Checkpoints go to models/<name>/; the final policy is models/<name>.zip, which
is loadable as a bot named <name> in play and eval. With --selfplay, each
checkpoint joins the opponent pool (keeping the most recent few).

Opponents are sampled uniformly; `name*3` in --opponents counts a bot three
times. --widen-from starts from a policy trained with a smaller encoder whose
features are a prefix of this one's (v2 -> v3): the new inputs get zero
weights, so the starting policy plays exactly like the old one.
"""

import argparse
import csv
import multiprocessing as mp
import multiprocessing.pool
import pathlib
import time

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import SubprocVecEnv, VecMonitor

from arena.eval import play_one
from arena.rl.env import DEFAULT_POOL, MirrormatchEnv

MODELS_DIR = pathlib.Path("models")


def parse_opponents(spec: str) -> list[str]:
    """'a,b*3' -> ['a', 'b', 'b', 'b'] (repeats make a bot more likely to be drawn)."""
    pool = []
    for item in spec.split(","):
        name, _, count = item.strip().partition("*")
        if name:
            pool += [name] * (int(count) if count else 1)
    return pool


def widen_from(model: PPO, source: str) -> None:
    """Copy a policy's weights into `model`, zero-padding the first layers for extra trailing inputs."""
    src = PPO.load(source, device="cpu").policy.state_dict()
    dst = model.policy.state_dict()
    for key, value in src.items():
        target = dst[key]
        if value.shape == target.shape:
            target.copy_(value)
        elif value.ndim == 2 and value.shape[0] == target.shape[0] and value.shape[1] < target.shape[1]:
            target.zero_()
            target[:, :value.shape[1]] = value
        else:
            raise ValueError(f"can't widen {key}: {tuple(value.shape)} -> {tuple(target.shape)}")
    model.policy.load_state_dict(dst)


def make_env(opponents: list[str], difficulty: str):
    def thunk():
        import torch

        torch.set_num_threads(1)
        return MirrormatchEnv(opponents, difficulty)
    return thunk


class EvalCallback(BaseCallback):
    """Every `every` steps: checkpoint, play the scripted pool, log win rates, update self-play pool."""

    def __init__(self, run_dir: pathlib.Path, every: int, games: int, difficulty: str,
                 scripted: list[str], opponents: list[str], selfplay_keep: int, pool: mp.pool.Pool) -> None:
        super().__init__()
        self.run_dir = run_dir
        self.every = every
        self.games = games
        self.difficulty = difficulty
        self.scripted = scripted
        self.opponents = opponents
        self.selfplay_keep = selfplay_keep
        self.pool = pool
        self.snapshots: list[str] = []
        self.next_eval = every
        self.started = time.time()
        self.log_path = run_dir / "progress.csv"

    def _on_step(self) -> bool:
        if self.num_timesteps >= self.next_eval:
            self.next_eval += self.every
            self.evaluate()
        return True

    def evaluate(self) -> dict[str, float]:
        ckpt = self.run_dir / f"step_{self.num_timesteps:09d}.zip"
        self.model.save(ckpt)
        rates = {}
        for opp in self.scripted:
            jobs = [(str(ckpt), opp, 10_000_000 + g, self.difficulty) for g in range(self.games)]
            outcomes = self.pool.map(play_one, jobs)
            wins = sum(1 for w, _ in outcomes if w == 0)
            losses = sum(1 for w, _ in outcomes if w == 1)
            rates[opp] = (wins, losses, self.games - wins - losses)
        elapsed = time.time() - self.started
        summary = "  ".join(f"{o} {w}-{l}-{d}" for o, (w, l, d) in rates.items())
        print(f"[{self.num_timesteps:>9,} steps, {elapsed / 60:5.1f} min] {summary}", flush=True)

        new = not self.log_path.exists()
        with self.log_path.open("a", newline="") as f:
            writer = csv.writer(f)
            if new:
                writer.writerow(["steps", "minutes", "opponent", "wins", "losses", "draws"])
            for o, (w, l, d) in rates.items():
                writer.writerow([self.num_timesteps, f"{elapsed / 60:.1f}", o, w, l, d])

        if self.selfplay_keep > 0:
            self.snapshots = (self.snapshots + [str(ckpt)])[-self.selfplay_keep:]
            self.training_env.env_method("set_opponents", self.opponents + self.snapshots)
        return rates


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Train a PPO policy against a pool of opponents.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--steps", type=int, default=5_000_000)
    parser.add_argument("--opponents", default=",".join(DEFAULT_POOL))
    parser.add_argument("--difficulty", default="normal")
    parser.add_argument("--envs", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--eval-every", type=int, default=500_000)
    parser.add_argument("--eval-games", type=int, default=40)
    parser.add_argument("--selfplay", type=int, default=0, help="keep this many recent checkpoints in the pool")
    parser.add_argument("--init", default=None, help="continue from this .zip")
    parser.add_argument("--widen-from", default=None, help="start from this .zip trained with a smaller encoder")
    args = parser.parse_args(argv)

    pool = parse_opponents(args.opponents)
    scripted = list(dict.fromkeys(pool))  # each opponent once, for the progress evals
    run_dir = MODELS_DIR / args.name
    run_dir.mkdir(parents=True, exist_ok=True)

    env = VecMonitor(SubprocVecEnv([make_env(pool, args.difficulty) for _ in range(args.envs)]))
    env.seed(args.seed)
    if args.init:
        model = PPO.load(args.init, env=env, device="cpu")
    else:
        model = PPO(
            "MlpPolicy", env,
            n_steps=1024, batch_size=2048, n_epochs=5,
            learning_rate=3e-4, gamma=0.995, gae_lambda=0.95,
            clip_range=0.2, ent_coef=0.01,
            policy_kwargs=dict(net_arch=[256, 256]),
            seed=args.seed, device="cpu", verbose=0,
        )
        if args.widen_from:
            widen_from(model, args.widen_from)
    with mp.get_context("spawn").Pool(args.envs) as workers:
        callback = EvalCallback(run_dir, args.eval_every, args.eval_games, args.difficulty,
                                scripted, pool, args.selfplay, workers)
        model.learn(total_timesteps=args.steps, callback=callback, reset_num_timesteps=args.init is None)
        callback.evaluate()
    final = MODELS_DIR / f"{args.name}.zip"
    model.save(final)
    env.close()
    print(f"saved {final}")


if __name__ == "__main__":
    main()
