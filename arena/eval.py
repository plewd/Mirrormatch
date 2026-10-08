"""Headless round robin: python -m arena.eval --bots a,b,c --games 200 --seed 0

Each pair plays `--games` games. Game g uses seed `seed + g` (random mirrored
spawns) and sides alternate: in even games the first bot is player 0. Every bot
is wrapped in the same difficulty preset. Results are printed as a matrix and
appended to results/log.csv.
"""

import argparse
import csv
import datetime as dt
import itertools
import multiprocessing as mp
import os
import pathlib
import subprocess
from dataclasses import dataclass

from arena.bots import make_bot
from arena.config import DEFAULT_CONFIG, DIFFICULTIES
from arena.fairness import FairController
from arena.match import run_match
from arena.sim.spawns import mirrored_random_spawns, spawn_rng

LOG_PATH = pathlib.Path("results/log.csv")
LOG_FIELDS = [
    "timestamp", "commit", "seed", "games", "difficulty",
    "bot_a", "bot_b", "a_wins", "b_wins", "draws", "avg_seconds",
]


@dataclass(frozen=True)
class PairResult:
    a: str
    b: str
    a_wins: int
    b_wins: int
    draws: int
    avg_seconds: float


def play_one(job: tuple[str, str, int, str]) -> tuple[int | None, int]:
    """Play one game; return (winner as 0 = bot a, 1 = bot b, None = draw; ticks)."""
    a, b, game_seed, difficulty = job
    cfg = DEFAULT_CONFIG
    preset = DIFFICULTIES[difficulty]
    bot_a = FairController(make_bot(a, cfg), preset)
    bot_b = FairController(make_bot(b, cfg), preset)
    a_first = game_seed % 2 == 0
    p0, p1 = (bot_a, bot_b) if a_first else (bot_b, bot_a)
    spawns = mirrored_random_spawns(cfg, spawn_rng(game_seed))
    res = run_match(p0, p1, cfg, game_seed, spawns)
    if res.winner is None:
        return None, res.ticks
    a_won = (res.winner == 0) == a_first
    return (0 if a_won else 1), res.ticks


def evaluate_pair(a: str, b: str, games: int, seed: int, difficulty: str, pool) -> PairResult:
    jobs = [(a, b, seed + g, difficulty) for g in range(games)]
    outcomes = pool.map(play_one, jobs, chunksize=max(1, games // 32)) if pool else list(map(play_one, jobs))
    a_wins = sum(1 for w, _ in outcomes if w == 0)
    b_wins = sum(1 for w, _ in outcomes if w == 1)
    ticks = sum(t for _, t in outcomes)
    return PairResult(a, b, a_wins, b_wins, games - a_wins - b_wins, ticks / games / DEFAULT_CONFIG.tick_rate)


def round_robin(bots: list[str], games: int, seed: int, difficulty: str, workers: int) -> list[PairResult]:
    pairs = list(itertools.combinations(bots, 2))
    if workers > 1:
        with mp.get_context("spawn").Pool(workers) as pool:
            return [evaluate_pair(a, b, games, seed, difficulty, pool) for a, b in pairs]
    return [evaluate_pair(a, b, games, seed, difficulty, None) for a, b in pairs]


def format_matrix(bots: list[str], results: list[PairResult]) -> str:
    """Rows are W-L-D from the row bot's point of view; last column is its overall win rate."""
    cell: dict[tuple[str, str], str] = {}
    totals = {b: [0, 0, 0] for b in bots}
    for r in results:
        cell[(r.a, r.b)] = f"{r.a_wins}-{r.b_wins}-{r.draws}"
        cell[(r.b, r.a)] = f"{r.b_wins}-{r.a_wins}-{r.draws}"
        for name, w, l in ((r.a, r.a_wins, r.b_wins), (r.b, r.b_wins, r.a_wins)):
            totals[name][0] += w
            totals[name][1] += l
            totals[name][2] += r.draws
    width = max(11, *(len(b) + 2 for b in bots))
    lines = ["W-L-D (row vs column)".ljust(width) + "".join(b.rjust(width) for b in bots) + "win %".rjust(8)]
    for row in bots:
        w, l, d = totals[row]
        n = w + l + d
        rate = f"{100 * w / n:.1f}" if n else "-"
        lines.append(row.ljust(width) + "".join(cell.get((row, col), "-").rjust(width) for col in bots) + rate.rjust(8))
    return "\n".join(lines)


def git_commit() -> str:
    """Short HEAD hash, with -dirty if tracked files outside results/ have changes."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no", "--", ".", ":!results"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def append_log(results: list[PairResult], seed: int, games: int, difficulty: str, path: pathlib.Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    commit = git_commit()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            writer.writeheader()
        for r in results:
            writer.writerow({
                "timestamp": stamp, "commit": commit, "seed": seed, "games": games,
                "difficulty": difficulty, "bot_a": r.a, "bot_b": r.b, "a_wins": r.a_wins,
                "b_wins": r.b_wins, "draws": r.draws, "avg_seconds": f"{r.avg_seconds:.2f}",
            })


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Round-robin bot evaluation.")
    parser.add_argument("--bots", required=True, help="comma-separated bot names")
    parser.add_argument("--games", type=int, default=200, help="games per pair")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--difficulty", default="normal", choices=sorted(DIFFICULTIES))
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--no-log", action="store_true", help="don't append to results/log.csv")
    args = parser.parse_args(argv)

    bots = [b.strip() for b in args.bots.split(",") if b.strip()]
    for b in bots:
        make_bot(b)  # fail fast on unknown names
    results = round_robin(bots, args.games, args.seed, args.difficulty, args.workers)
    print(f"{args.games} games per pair, seed {args.seed}, difficulty {args.difficulty}\n")
    print(format_matrix(bots, results))
    print("\navg game length (s): " + ", ".join(f"{r.a}-{r.b} {r.avg_seconds:.1f}" for r in results))
    if not args.no_log:
        append_log(results, args.seed, args.games, args.difficulty)
        print(f"\nlogged to {LOG_PATH}")


if __name__ == "__main__":
    main()
