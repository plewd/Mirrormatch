"""Host the browser version locally.

    python -m arena.web fetch            # once: download the pinned Pyodide runtime and Blockly into web/vendor/
    python -m arena.web serve [--host 0.0.0.0] [--port 8000]

`serve` bundles the `arena` package (the same sim the CLI uses) into web/build/,
then serves web/ with the standard library's HTTP server. Use --host 0.0.0.0 to
let friends on your network open http://<your-ip>:8000.
"""

import argparse
import functools
import hashlib
import http.server
import json
import pathlib
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
VENDOR = WEB / "vendor"
BUILD = WEB / "build"
BOTS = ROOT / "bots"

PYODIDE_VERSION = "314.0.7"
PYODIDE_CORE = (
    "pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json",
)
PYODIDE_PACKAGES = ("numpy",)  # wheels taken from the lock file, checksum-verified

BLOCKLY_VERSION = "13.3.0"  # block editor (Apache-2.0); one browser bundle with English messages
BLOCKLY_SHA256 = "ff9d8dc68e095890c6eb64962ca76130f9c3f49f0bc647076ee2f825f328de48"

# The browser needs the sim, bots, fairness wrapper and RL feature encoders (for exported policies).
# Not the pygame front end, RL training, eval, or the server.
BUNDLE_EXCLUDE = (
    "arena/rl/env.py", "arena/rl/train.py", "arena/rl/export.py",
    "arena/play.py", "arena/render.py", "arena/eval.py", "arena/web.py",
)
MODELS = ROOT / "models"


def _download(url: str, dest: pathlib.Path) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return data


def fetch() -> None:
    target = VENDOR / "pyodide"
    target.mkdir(parents=True, exist_ok=True)
    core = f"https://cdn.jsdelivr.net/npm/pyodide@{PYODIDE_VERSION}/"
    for name in PYODIDE_CORE:
        print(f"fetching {name}")
        _download(core + name, target / name)
    lock = json.loads((target / "pyodide-lock.json").read_text())
    full = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
    for pkg in PYODIDE_PACKAGES:
        info = lock["packages"][pkg]
        print(f"fetching {info['file_name']}")
        data = _download(full + info["file_name"], target / info["file_name"])
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            (target / info["file_name"]).unlink()
            raise SystemExit(f"checksum mismatch for {info['file_name']}; deleted it")
    print(f"Pyodide {PYODIDE_VERSION} is in {target}")

    blockly = VENDOR / "blockly"
    blockly.mkdir(parents=True, exist_ok=True)
    print("fetching blockly.min.js")
    data = _download(f"https://cdn.jsdelivr.net/npm/blockly@{BLOCKLY_VERSION}/blockly.min.js", blockly / "blockly.min.js")
    if hashlib.sha256(data).hexdigest() != BLOCKLY_SHA256:
        (blockly / "blockly.min.js").unlink()
        raise SystemExit("checksum mismatch for blockly.min.js; deleted it")
    print(f"Blockly {BLOCKLY_VERSION} is in {blockly}")


def build() -> None:
    """Zip the arena package and write the bot / vocabulary indexes the page loads."""
    from arena.bots.rules import vocabulary

    BUILD.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BUILD / "arena.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted((ROOT / "arena").rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if not rel.startswith(BUNDLE_EXCLUDE):
                zf.write(path, rel)
        # Trained policies become ladder bots: the shipped ones in policies/, plus (overriding by
        # name) any you exported yourself into models/ with `python -m arena.rl.export`.
        found = {}
        for folder in (ROOT / "policies", MODELS):
            for path in sorted(folder.glob("*.npz")) if folder.is_dir() else []:
                found[path.name] = path
        for name, path in sorted(found.items()):
            zf.write(path, f"policies/{name}")
    starters = {p.stem: json.loads(p.read_text()) for p in sorted(BOTS.glob("*.json"))}
    (BUILD / "bots.json").write_text(json.dumps(starters, indent=1))
    (BUILD / "vocab.json").write_text(json.dumps(vocabulary(), indent=1))


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm", ".mjs": "text/javascript", ".js": "text/javascript", ".json": "application/json",
    }

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")  # always pick up a fresh build during development
        super().end_headers()


def serve(host: str, port: int) -> None:
    if not (VENDOR / "pyodide" / "pyodide.mjs").exists():
        raise SystemExit("Pyodide isn't downloaded yet: run `python -m arena.web fetch` once first.")
    build()
    handler = functools.partial(Handler, directory=str(WEB))
    with http.server.ThreadingHTTPServer((host, port), handler) as httpd:
        shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
        print(f"Mirrormatch is running at http://{shown}:{port}  (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Mirrormatch in the browser.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="download the Pyodide runtime (once)")
    sub.add_parser("build", help="bundle the game for the browser without serving")
    srv = sub.add_parser("serve", help="bundle and serve the game")
    srv.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to allow other machines on your network")
    srv.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.cmd == "fetch":
        fetch()
    elif args.cmd == "build":
        build()
    else:
        serve(args.host, args.port)


if __name__ == "__main__":
    main()
