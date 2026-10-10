import dataclasses
import hashlib
import json
import pathlib
import shutil
import subprocess
import zipfile

import pytest

from arena import web
from arena.webapi import HUMAN, Session, arena_info, check_bot, run_series

ROOT = pathlib.Path(__file__).parent.parent


def digest(session: Session) -> str:
    return hashlib.sha256(json.dumps(dataclasses.asdict(session.game.state), sort_keys=True).encode()).hexdigest()[:16]


def test_human_session_commands_and_snapshot():
    s = Session(HUMAN, "idle", "normal", seed=3)
    me = s.game.state.champions[0]
    s.command(json.dumps({"move": [me.x + 200, me.y]}))
    snap = json.loads(s.advance(5))
    assert snap["tick"] == 5 and snap["champions"][0]["x"] > me.x - 1e-9
    assert set(snap) >= {"time_left", "done", "winner", "projectiles", "walls", "zones", "pickups"}
    s.command(json.dumps({"cast": "bolt", "aim": [600, 400]}))
    snap = json.loads(s.advance(1))
    assert snap["champions"][0]["cast"]["ability"] == "bolt"
    s.command(json.dumps({"cast": "item", "aim": [600, 400]}))  # empty slot: ignored
    s.game.state.champions[0].item = "shield"
    s.advance(10)
    s.command(json.dumps({"cast": "item", "aim": [600, 400]}))
    assert json.loads(s.advance(1))["champions"][0]["shielded"]


def test_rule_bot_json_and_builtin_names_both_work():
    spec = (ROOT / "bots" / "dodger.json").read_text()
    a = Session(spec, "leader", seed=1)
    b = Session("bots/dodger.json", "leader", seed=1)
    a.advance(400)
    b.advance(400)
    assert digest(a) == digest(b)


def test_series_check_and_info():
    res = json.loads(run_series("dodger", "aimer", 4))
    assert res == {"wins": 4, "losses": 0, "draws": 0}
    assert json.loads(check_bot('{"rules": [{"then": {"action": "fly"}}]}'))
    assert json.loads(check_bot((ROOT / "bots" / "leader.json").read_text())) == []
    assert json.loads(check_bot("{nope")) [0].startswith("not valid JSON")
    assert json.loads(arena_info())["width"] == 1200


def test_bundle_has_the_sim_but_not_the_desktop_or_training_code():
    web.build()
    names = zipfile.ZipFile(web.BUILD / "arena.zip").namelist()
    assert "arena/sim/game.py" in names and "arena/webapi.py" in names and "arena/bots/rules.py" in names
    assert "arena/rl/features.py" in names  # needed by exported policies
    assert not any(n.startswith(("arena/rl/env.py", "arena/rl/train.py", "arena/play.py", "arena/render.py")) for n in names)
    folders = (web.ROOT / "policies", web.MODELS)  # shipped policies plus your own exports
    exported = sorted({p.name for d in folders if d.is_dir() for p in d.glob("*.npz")})
    assert sorted(n.split("/")[1] for n in names if n.startswith("policies/")) == exported
    assert "leader" in json.loads((web.BUILD / "bots.json").read_text())
    assert "actions" in json.loads((web.BUILD / "vocab.json").read_text())
    offline = json.loads((web.BUILD / "files.json").read_text())  # what sw.js saves for offline play
    assert {"index.html", "app.js", "style.css", "manifest.webmanifest", "build/arena.zip"} <= set(offline)
    assert "sw.js" not in offline and "build/files.json" not in offline
    assert all((web.ROOT / "web" / f).is_file() for f in offline)


@pytest.mark.skipif(shutil.which("node") is None or not (web.VENDOR / "pyodide" / "pyodide.mjs").exists(),
                    reason="needs node and `python -m arena.web fetch`")
def test_browser_runtime_plays_bit_identical_games(tmp_path):
    """The same match in Pyodide (WebAssembly) and CPython must end in the same state."""
    web.build()
    script = tmp_path / "digest.py"
    script.write_text(
        "import sys, hashlib, json, dataclasses\n"
        "sys.path.insert(0, '/home/pyodide')\n"
        "from arena.webapi import Session\n"
        "s = Session('dodger', 'leader', 'normal', seed=7)\n"
        "s.advance(3000)\n"
        "hashlib.sha256(json.dumps(dataclasses.asdict(s.game.state), sort_keys=True).encode()).hexdigest()[:16]\n"
    )
    out = subprocess.run(["node", str(ROOT / "web" / "node_check.mjs"), str(script)],
                         capture_output=True, text=True, timeout=240)
    assert out.returncode == 0, out.stderr[-2000:]
    browser_digest = out.stdout.strip().splitlines()[-1]
    native = Session("dodger", "leader", "normal", seed=7)
    native.advance(3000)
    assert browser_digest == digest(native)


def test_replay_reenacts_a_human_match_exactly():
    s = Session(HUMAN, "dodger", "normal", seed=11)
    rng = __import__("numpy").random.default_rng(5)
    while not s.game.state.done:
        if rng.random() < 0.1:
            s.command(json.dumps({"move": [float(rng.uniform(0, 1200)), float(rng.uniform(0, 800))]}))
        if rng.random() < 0.05:
            s.command(json.dumps({"cast": ["bolt", "dash", "item"][int(rng.integers(3))], "aim": [600.0, 400.0]}))
        s.advance(int(rng.integers(1, 4)))  # uneven batches, like browser frames
    replay = s.replay("You", "dodger")
    again = Session.from_replay(json.loads(json.dumps(replay)))  # survives a save/load round trip
    while not again.game.state.done:
        again.advance(7)
    assert digest(again) == digest(s)
    assert json.loads(replay)["left"]["label"] == "You"


def test_bot_vs_bot_replay_and_bad_file():
    s = Session("dodger", "bots/leader.json", seed=2)
    s.advance(5000)
    again = Session.from_replay(s.replay())
    again.advance(5000)
    assert digest(again) == digest(s)
    with pytest.raises(ValueError):
        Session.from_replay('{"seed": 1}')


def test_timeline_seek_matches_straight_playback():
    ref = Session("bots/baiter.json", "dodger", seed=21)
    states = {}
    while not ref.game.state.done:
        ref.advance(1)
        states[ref.game.state.tick] = digest(ref)
    s = Session("bots/baiter.json", "dodger", seed=21)
    length = s.prepare_timeline()
    assert length == ref.game.state.tick and s.game.state.tick == 0  # prepared, but still at the start
    assert len(s.checkpoints) >= length // 150
    for t in [37, 500, 20, length, 151, 150, 149, 1]:  # forward, back, to the end, across checkpoints
        if t > length:
            continue
        s.seek(t)
        assert s.game.state.tick == t and digest(s) == states[t], t


def test_timeline_works_for_replays_of_human_games():
    import numpy as np

    live = Session(HUMAN, "dodger", seed=4)
    rng = np.random.default_rng(1)
    while not live.game.state.done:
        if rng.random() < 0.1:
            live.command(json.dumps({"move": [float(rng.uniform(0, 1200)), float(rng.uniform(0, 800))]}))
        if rng.random() < 0.05:
            live.command(json.dumps({"cast": "bolt", "aim": [600.0, 400.0]}))
        live.advance(2)
    with pytest.raises(ValueError):
        Session(HUMAN, "dodger", seed=4).prepare_timeline()  # live play has no known end
    rep = Session.from_replay(live.replay())
    assert rep.prepare_timeline() == live.game.state.tick
    rep.seek(live.game.state.tick)
    assert digest(rep) == digest(live)
    rep.seek(10)
    rep.seek(live.game.state.tick)
    assert digest(rep) == digest(live)


def test_snapshots_hand_over_new_events_once():
    s = Session("bots/baiter.json", "dodger", seed=21)
    seen = []
    while not s.game.state.done:
        seen += json.loads(s.advance(5))["events"]
    kinds = {e[0] for e in seen}
    assert {"cast", "hit", "damage"} <= kinds and all(isinstance(e[-1], int) for e in seen)  # tick is last
    assert json.loads(s.snapshot())["events"] == []  # already handed over


def test_seeks_and_timeline_prep_do_not_emit_events():
    s = Session("bots/baiter.json", "dodger", seed=21)
    length = s.prepare_timeline()
    assert json.loads(s.snapshot())["events"] == []
    assert json.loads(s.seek(length - 1))["events"] == []
    assert json.loads(s.seek(5))["events"] == []


def test_snapshots_show_what_each_bot_saw_in_world_coordinates():
    """debug[i]["seen"] is the delayed view behind bot i's last decision, un-mirrored for the right side."""
    s = Session("aimer", "aimer", "normal", seed=2)
    snaps = {0: json.loads(s.snapshot())}
    threats = [0, 0]
    while not snaps[max(snaps)]["done"] and max(snaps) < 300:
        snap = json.loads(s.advance(1))
        snaps[snap["tick"]] = snap
        for i, d in enumerate(snap["debug"]):
            seen = d["seen"]
            then = snaps[seen["tick"]]
            assert 0 <= snap["tick"] - seen["tick"] <= 6 + 3  # reaction delay plus the decision interval (normal)
            assert seen["age"] == pytest.approx((snap["tick"] - seen["tick"]) / 30)
            me, enemy = then["champions"][i], then["champions"][1 - i]
            assert seen["me"] == pytest.approx([me["x"], me["y"]])
            assert seen["enemy"] == pytest.approx([enemy["x"], enemy["y"]])
            real = sorted((p["x"], p["y"]) for p in then["projectiles"] if p["owner"] != i)
            got = sorted((p["x"], p["y"]) for p in seen["projectiles"])
            assert [v for xy in got for v in xy] == pytest.approx([v for xy in real for v in xy])
            if seen["threat"] is not None:
                threats[i] += 1
                assert 0 <= seen["threat"] < len(seen["projectiles"])
    assert threats[0] > 0 and threats[1] > 0  # two aimers shooting at each other: both see shots coming


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_share_links_round_trip_and_refuse_bad_data(tmp_path):
    """web/share.js: bots and replays survive pack -> unpack; damaged or oversized data is refused."""
    bot = (ROOT / "bots" / "baiter.json").read_text()
    s = Session(bot, "dodger", seed=5)  # like the browser: the replay embeds the bot's full spec
    s.advance(10**6)
    replay = s.replay("baiter", "dodger")
    module = tmp_path / "share.mjs"  # node reads a bare .js as CommonJS; the page loads it as a module
    module.write_text((ROOT / "web" / "share.js").read_text())
    script = tmp_path / "share_check.mjs"
    script.write_text(f"""
import {{ pack, unpack }} from {json.dumps(module.as_uri())};
const out = {{}};
for (const [name, text] of Object.entries({json.dumps({"bot": bot, "replay": replay})})) {{
  const packed = await pack(text);
  out[name] = {{ same: (await unpack(packed)) === text, urlSafe: /^[A-Za-z0-9_-]+$/.test(packed), ratio: packed.length / text.length }};
}}
try {{ await unpack("not-a-valid-payload"); out.damaged = "accepted"; }} catch {{ out.damaged = "refused"; }}
const bomb = await pack("x".repeat(3 << 20));  // tiny when packed, 3 MB when inflated
try {{ await unpack(bomb); out.bomb = "accepted"; }} catch {{ out.bomb = "refused"; }}
console.log(JSON.stringify(out));
""")
    res = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout)
    for name in ("bot", "replay"):
        assert res[name]["same"] and res[name]["urlSafe"] and res[name]["ratio"] < 0.6
    assert res["damaged"] == "refused" and res["bomb"] == "refused"
