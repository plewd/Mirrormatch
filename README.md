# Mirrormatch

A 1v1 top-down skillshot duel you can play in the browser, against bots you can build yourself.

**▶ Play: https://plewd.github.io/Mirrormatch/**

Two champions, 3 HP each, 90 seconds. Land your shots, dodge theirs, fight over pickups and the
center heal. The opponents are bots: hand-written ones, ones you snap together from rule blocks,
and neural-network bots trained with reinforcement learning.

## The game

- **Bolt (Q):** your main shot. Casting roots you for a moment, which is when you're easiest to hit.
- **Dash (W):** a quick burst toward the cursor, on a 5 s cooldown.
- **Pickups (E):** one appears every 5 s, always the same distance from both players, so it's a fair race.
  You hold one at a time, single use: boomerang, shield (a successful block also heals 1 HP), root, wall,
  hook or blast.
- **Center heal:** an orb at the center appears at 15 s, and again 15 s after each time it's taken.
- At 0 HP you lose. At the time limit, more HP wins; equal HP is a draw.

## In the browser

- **Play:** pick an opponent (the bars show how strong each one is) and a difficulty. Difficulty
  never changes game speed; it sets how human the bots are: how late they react, how often they
  decide, and how precisely they aim.
- **Watch:** any bot against any bot, with a timeline (pause, step, scrub, ¼× to 8×). It can show each
  rule bot's rules as they fire, what each bot decided, and what each bot sees (bots react to a
  slightly old view of the game, just like a person).
- **Build:** make your own bot from rule blocks ("if a shot is coming at me → strafe"), preview it
  fighting, test it, then play it or watch it.
- **Tournament:** a round robin between any bots you pick, with standings and a head-to-head grid.
- **Guide:** the rules, every ability's numbers, and how bots think.

### Sharing

- **Bots:** in Build, **Bot ▾ → Copy share link**. Anyone who opens the link can play your bot, watch it
  fight, open it in Build, or save it to their own bots.
- **Matches:** in Watch, **Replays & files ▾ → Copy replay link**.

The bot or replay travels inside the link itself (compressed), so there's no account and no server.
Bots are plain rule data, never code.

## Run it locally

Python 3.11+.

```
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -m arena.web fetch      # once: the pinned Pyodide runtime and Blockly, checksum-verified, into web/vendor/
python -m arena.web serve      # http://localhost:8000  (--host 0.0.0.0 to share on your network)
```

The browser version runs the same Python simulation through Pyodide, so everything above works
offline once fetched.

There's also a desktop front end and command-line tools:

```
python -m arena.play --opponent dodger --difficulty normal     # pygame window
python -m arena.eval --bots aimer,leader,dodger,bots/baiter.json,ppo_v3 --games 200   # round robin
python -m arena.bots.rules check bots/*.json                   # validate rule bots
pytest                                                         # tests
```

### Training bots

```
pip install -e ".[dev,rl]"     # gymnasium, stable-baselines3, torch
python -m arena.rl.train --name my_bot --steps 5000000 --selfplay 5
python -m arena.rl.export my_bot    # numpy weights in models/, so the bot also runs in the browser
```

The shipped trained bots (`ppo_v1` to `ppo_v3`) are in `policies/`.

## How it's built

- `arena/sim/`: a deterministic, headless simulation (fixed 30 ticks per second, seeded randomness).
  The same seed and inputs always play out identically, in CPython and in the browser. Each ability
  is its own file in `arena/sim/abilities/`.
- `arena/config.py`: every tunable number.
- `arena/bots/`: the scripted bots, the rule language for block-built bots (`rules.py`), and trained
  policies run with plain numpy.
- `arena/fairness.py`: reaction delay, decision rate and aim noise, applied to every bot the same way.
- `arena/rl/`: the Gymnasium environment, feature encoders and training.
- `arena/webapi.py`, `web/`: the browser front end (canvas renderer, Blockly editor, sound).

## License

This project is licensed under the plewd License. All rights reserved.
