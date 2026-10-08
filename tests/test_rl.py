import dataclasses

import numpy as np
import pytest

pytest.importorskip("gymnasium")
pytest.importorskip("stable_baselines3")

from gymnasium.utils.env_checker import check_env  # noqa: E402

from arena.bots import make_bot  # noqa: E402
from arena.config import DEFAULT_CONFIG, Difficulty  # noqa: E402
from arena.fairness import FairController  # noqa: E402
from arena.match import controller_rng  # noqa: E402
from arena.rl.env import MirrormatchEnv  # noqa: E402
from arena.rl.features import (  # noqa: E402
    ABILITY_DASH, ABILITY_ITEM, MOVE_STOP, OBS_SIZE, FeatureEncoder, FeatureEncoderV2, FeatureEncoderV3,
    encoder_for_obs_size,
)
from arena.sim.game import Game  # noqa: E402
from arena.sim.spawns import mirrored_random_spawns, spawn_rng  # noqa: E402
from arena.sim.state import Pickup, Wall, Zone  # noqa: E402
from arena.sim.types import Vec2  # noqa: E402
from stable_baselines3 import PPO  # noqa: E402

from arena.match import run_match  # noqa: E402


def scripted_policy(features: np.ndarray, nvec) -> np.ndarray:
    """A deterministic function of the features, standing in for a trained net."""
    k = int(abs(features[:4].sum()) * 1000)
    return np.array([k % nvec[0], (k // 10) % nvec[1], (k // 40) % nvec[2]])


class ScriptedPolicyBot:
    def __init__(self, encoder):
        self.encoder = encoder

    def reset(self, rng):
        pass

    def act(self, obs):
        return self.encoder.decode(scripted_policy(self.encoder.encode(obs), self.encoder.action_nvec), obs)


def test_env_passes_gymnasium_checks():
    check_env(MirrormatchEnv(), skip_render_check=True)


def test_encoding_shape_and_decoding():
    enc = FeatureEncoder(DEFAULT_CONFIG)
    game = Game(DEFAULT_CONFIG, 0)
    obs = game.observe(0)
    assert enc.encode(obs).shape == (OBS_SIZE,)
    stop = enc.decode([MOVE_STOP, 0, 0], obs)
    assert stop.move == obs.me.pos and stop.cast is None
    east = enc.decode([2, 1, 7], obs)  # direction 0 = +x; aim bin 7 = enemy's current position
    assert east.move == Vec2(obs.me.pos.x + 150, obs.me.pos.y)
    assert east.cast.aim == obs.enemy.pos


@pytest.mark.parametrize("encoder", ["v1", "v2", "v3"])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_env_matches_fair_controller_exactly(seed, encoder):
    """The env's built-in delay/rate limit must produce the same game as wrapping the
    same policy in FairController. (Aim noise off: the two draw it from differently
    arranged streams.)"""
    preset = Difficulty(reaction_delay=6, rate_limit=3, aim_noise_deg=0.0)
    env = MirrormatchEnv(opponents=["dodger"], difficulty=preset, encoder=encoder)
    feats, _ = env.reset(seed=seed)
    done = False
    while not done:
        feats, _, done, _, _ = env.step(scripted_policy(feats, env.encoder.action_nvec))

    side = env.side
    game = Game(DEFAULT_CONFIG, env.game_seed, mirrored_random_spawns(DEFAULT_CONFIG, spawn_rng(env.game_seed)))
    agent = FairController(ScriptedPolicyBot(env.encoder), preset)
    opp = FairController(make_bot("dodger"), preset)
    agent.reset(controller_rng(env.game_seed, side))
    opp.reset(controller_rng(env.game_seed, 1 - side))
    while not game.state.done:
        a_agent = agent.act(game.observe(side))
        a_opp = opp.act(game.observe(1 - side))
        game.step(*((a_agent, a_opp) if side == 0 else (a_opp, a_agent)))
    assert dataclasses.asdict(game.state) == dataclasses.asdict(env.game.state)


def test_rewards_and_terminal_info():
    env = MirrormatchEnv(opponents=["idle"])
    env.reset(seed=0)
    total, done, info = 0.0, False, {}
    while not done:
        _, r, done, _, info = env.step(np.array([MOVE_STOP, 0, 0]))
        total += r
    assert info == {"winner": None, "opponent": "idle"}
    assert total == 0.0


@pytest.mark.parametrize("encoder", ["v1", "v2", "v3"])
def test_saved_policy_loads_as_a_bot_with_its_encoder(tmp_path, encoder):
    model = PPO("MlpPolicy", MirrormatchEnv(encoder=encoder), n_steps=64, batch_size=64, device="cpu")
    path = tmp_path / f"tiny_{encoder}.zip"
    model.save(path)
    bot = make_bot(str(path))
    assert isinstance(bot.encoder, {"v1": FeatureEncoder, "v2": FeatureEncoderV2, "v3": FeatureEncoderV3}[encoder])
    res = run_match(bot, make_bot("aimer"), seed=0)
    assert res.ticks > 0


def test_v2_encodes_map_entities_and_decodes_the_kit():
    enc = FeatureEncoderV2(DEFAULT_CONFIG)
    game = Game(DEFAULT_CONFIG, 0)
    s = game.state
    s.walls.append(Wall(600, 300, 600, 500, 1, 30))
    s.zones.append(Zone("blast", 1, 300, 300, 110, 1, 10))
    s.pickups.append(Pickup(400, 600, "hook"))
    s.champions[0].item = "wall"
    obs = game.observe(0)
    empty = enc.encode(Game(DEFAULT_CONFIG, 0).observe(0))
    full = enc.encode(obs)
    assert full.shape == empty.shape == (enc.obs_size,)
    assert np.count_nonzero(full) > np.count_nonzero(empty)
    assert encoder_for_obs_size(enc.obs_size, DEFAULT_CONFIG).__class__ is FeatureEncoderV2

    dash = enc.decode([MOVE_STOP, ABILITY_DASH, 2], obs)  # compass bin 2 = straight down (+y)
    assert dash.cast.ability_id == "dash" and dash.cast.aim == Vec2(obs.me.pos.x, obs.me.pos.y + 100)
    wall = enc.decode([0, ABILITY_ITEM, 0], obs)
    assert wall.cast.ability_id == "wall" and wall.cast.aim.x == pytest.approx(obs.me.pos.x + 80)
    s.champions[0].item = None
    assert enc.decode([0, ABILITY_ITEM, 0], game.observe(0)).cast is None


def test_v3_is_v2_plus_the_heal_in_the_mirrored_frame():
    v2, v3 = FeatureEncoderV2(DEFAULT_CONFIG), FeatureEncoderV3(DEFAULT_CONFIG)
    game = Game(DEFAULT_CONFIG, 0, ((300, 200), (900, 200)))
    left, right = v3.encode(game.observe(0)), v3.encode(game.observe(1))
    assert left.shape == (v3.obs_size,) == (v2.obs_size + 4,)
    np.testing.assert_array_equal(left[:v2.obs_size], v2.encode(game.observe(0)))
    np.testing.assert_allclose(left[-4:], [0.0, 0.25, 0.25, 1.0])  # not up; center is right and below; 15 s away
    np.testing.assert_allclose(right[-4:], left[-4:])  # mirror-image spawns see the same thing
    assert encoder_for_obs_size(v3.obs_size, DEFAULT_CONFIG).__class__ is FeatureEncoderV3

    game.state.heal_up = True
    up = v3.encode(game.observe(0))
    assert up[-4] == 1.0 and up[-1] == 0.0


@pytest.mark.parametrize("encoder", ["v1", "v2", "v3"])
def test_exported_numpy_policy_acts_exactly_like_torch(tmp_path, encoder):
    from arena.bots.numpy_policy import NumpyPolicyBot
    from arena.bots.policy import PolicyBot
    from arena.rl.export import export

    env = MirrormatchEnv(encoder=encoder)
    model = PPO("MlpPolicy", env, n_steps=64, batch_size=64, device="cpu", policy_kwargs=dict(net_arch=[32, 32]), seed=0)
    model.learn(128)  # move the weights off their initial values (seeded: the same weights every run)
    path = tmp_path / "tiny.zip"
    model.save(path)
    export(path, tmp_path / "tiny.npz")
    torch_bot, numpy_bot = PolicyBot(path), NumpyPolicyBot(tmp_path / "tiny.npz")
    game = Game(DEFAULT_CONFIG, 3)
    opp = make_bot("dodger")
    checked = 0
    while not game.state.done and checked < 400:
        obs = game.observe(0)
        assert torch_bot.act(obs) == numpy_bot.act(obs)
        game.step(torch_bot.act(obs), opp.act(game.observe(1)))
        checked += 1
    assert checked > 50
    assert isinstance(make_bot(str(tmp_path / "tiny.npz")), NumpyPolicyBot)


def test_opponent_weights_repeat_names():
    from arena.rl.train import parse_opponents

    assert parse_opponents("aimer, bots/baiter.json*3,,ppo_v2*2") == (
        ["aimer"] + ["bots/baiter.json"] * 3 + ["ppo_v2"] * 2)


def test_widened_v2_policy_plays_exactly_like_the_original(tmp_path):
    from arena.rl.train import widen_from

    # Seeded, so the weights (and any near-tie between actions) are the same every run.
    kw = dict(n_steps=64, batch_size=64, device="cpu", policy_kwargs=dict(net_arch=[32, 32]), seed=0)
    old = PPO("MlpPolicy", MirrormatchEnv(encoder="v2"), **kw)
    old.learn(128)
    old.save(tmp_path / "old.zip")
    new = PPO("MlpPolicy", MirrormatchEnv(encoder="v3"), **kw)
    widen_from(new, str(tmp_path / "old.zip"))

    v2, v3 = FeatureEncoderV2(DEFAULT_CONFIG), FeatureEncoderV3(DEFAULT_CONFIG)
    game, opp = Game(DEFAULT_CONFIG, 5), make_bot("dodger")
    compared = 0
    while not game.state.done and compared < 300:
        obs = game.observe(0)
        a_old, _ = old.predict(v2.encode(obs), deterministic=True)
        a_new, _ = new.predict(v3.encode(obs), deterministic=True)
        np.testing.assert_array_equal(a_old, a_new)
        game.step(v2.decode(a_old, obs), opp.act(game.observe(1)))
        compared += 1
    assert compared > 90  # dodger can't win in under ~3.3 s (three bolts), so this always sees 99+ decisions
