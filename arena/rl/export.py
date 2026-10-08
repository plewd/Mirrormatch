"""Export trained PPO policies to numpy weights: python -m arena.rl.export ppo_v1 ppo_v2

Writes models/<name>.npz next to models/<name>.zip. The exported policy acts
exactly like the deterministic SB3 policy (tested) but needs only numpy, so it
runs in the browser.
"""

import argparse
import pathlib

import numpy as np

MODELS = pathlib.Path("models")


def export(zip_path: pathlib.Path, out: pathlib.Path) -> None:
    from stable_baselines3 import PPO

    model = PPO.load(zip_path, device="cpu")
    sd = {k: v.detach().cpu().numpy().astype(np.float32) for k, v in model.policy.state_dict().items()}
    linear = sorted({int(k.split(".")[2]) for k in sd if k.startswith("mlp_extractor.policy_net.") and k.endswith(".weight")})
    arrays = {}
    for i, idx in enumerate(linear):
        arrays[f"w{i}"] = sd[f"mlp_extractor.policy_net.{idx}.weight"]
        arrays[f"b{i}"] = sd[f"mlp_extractor.policy_net.{idx}.bias"]
    arrays["wa"] = sd["action_net.weight"]
    arrays["ba"] = sd["action_net.bias"]
    arrays["nvec"] = np.asarray(model.action_space.nvec, dtype=np.int64)
    arrays["hidden_layers"] = np.asarray(len(linear))
    np.savez_compressed(out, **arrays)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export trained policies to numpy .npz weights.")
    parser.add_argument("names", nargs="+", help="model names in models/ (or .zip paths)")
    args = parser.parse_args(argv)
    for name in args.names:
        src = pathlib.Path(name) if name.endswith(".zip") else MODELS / f"{name}.zip"
        out = src.with_suffix(".npz")
        export(src, out)
        print(f"{src} -> {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
