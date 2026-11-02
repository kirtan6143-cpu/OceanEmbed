"""One-command V2 regeneration of every artifact that depends on demo.nc.

Run this AFTER the real demo.nc (and its demo.metrics.json from `oceanembed
predict` / the Colab ensemble bridge) has been placed in demo/runs/.

    python scripts/regenerate_v2_artifacts.py demo/runs/demo.nc \
        --argo-csv data/observations/argo.csv \
        --cyclone-config configs/cyclone.remal.yaml

Steps (fails fast; nothing stale is reused):
  1. delete any existing dependent artifacts next to demo.nc
  2. Argo held-out 'test' matchups  -> argo_validation.json
  3. cyclone thermal context        -> cyclone_context.json
  4. cold-wake pre/post windows     -> cold_wake.json
  5. release verifier + manifest    -> RELEASE_MANIFEST.json
All output is also written to regeneration.log.
"""
import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from oceanembed.cyclone import cold_wake, load_track, thermal_context  # noqa: E402
from oceanembed.observations import match  # noqa: E402
import verify_demo_artifacts as gate  # noqa: E402

DERIVED = ["argo_validation.json", "cyclone_context.json", "cold_wake.json", "RELEASE_MANIFEST.json"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--argo-csv", type=Path)
    ap.add_argument("--cyclone-config", type=Path, default=ROOT / "configs/cyclone.remal.yaml")
    ap.add_argument("--wake-depth", type=float, default=50.0)
    ap.add_argument("--wake-days", type=int, default=3)
    ap.add_argument("--allow-synthetic", action="store_true", help="rehearse on the synthetic fixture (skips Argo)")
    args = ap.parse_args(argv)

    run = args.run.resolve()
    out = run.parent
    log_lines = []

    def log(msg):
        print(msg)
        log_lines.append(str(msg))

    if not run.exists():
        raise SystemExit(f"{run} not found - regenerate demo.nc first (Colab ensemble bridge / oceanembed predict)")
    if not (out / "demo.metrics.json").exists():
        raise SystemExit("demo.metrics.json missing - it must be produced by the same inference run as demo.nc")

    for name in DERIVED:
        (out / name).unlink(missing_ok=True)
    log(f"run: {run}\nrun_sha256: {gate.sha256(run)}")

    if args.allow_synthetic:
        log("[1/4] Argo: SKIPPED (synthetic rehearsal - real observations cannot validate a synthetic run)")
    else:
        if not args.argo_csv:
            raise SystemExit("--argo-csv is required for a real release")
        r = match(run, args.argo_csv, out / "argo_validation.json", "test")
        log(f"[1/4] Argo test matchups: {len(r['matchups'])} from {len(r['float_ids'])} floats")

    cfg = yaml.safe_load(args.cyclone_config.read_text())
    if not Path(cfg["path"]).is_absolute():
        cfg["path"] = str(ROOT / cfg["path"])
    track = load_track(cfg)
    c = thermal_context(run, track, out / "cyclone_context.json")
    log(f"[2/4] cyclone-context: {c['points_with_thermal_context']}/{c['points_total']} track points")
    w = cold_wake(run, track, args.wake_depth, args.wake_days, out / "cold_wake.json")
    log(f"[3/4] cold-wake: {w['locations_with_complete_windows']}/{w['locations_total']} complete windows, "
        f"mean change {w['mean_change_degC']}")

    argv_gate = [str(run), "--manifest", str(out / "RELEASE_MANIFEST.json")]
    if args.allow_synthetic:
        argv_gate.append("--allow-synthetic")
    log("[4/4] release verifier")
    code = gate.main(argv_gate)
    log(f"verifier exit code: {code}")
    (out / "regeneration.log").write_text("\n".join(log_lines) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
