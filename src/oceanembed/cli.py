"""Numbered workflow entry points: python -m oceanembed.cli --help."""

import argparse
import json
from pathlib import Path
import shutil
import sys
import yaml
import numpy as np
from .contracts import dump, load_cube, save_nc, DEPTHS, sha256


def demo_run(cube, out):
    ds = load_cube(cube).isel(time=slice(-45, None))
    rng = np.random.default_rng(7)
    ds["reference"] = ds.target
    # Not a trained model. Explicit engineering illustration with a known reference.
    ds["temperature"] = ds.target + (
        0.12 * np.sin(np.arange(len(ds.time)))[:, None, None, None]
    )
    ds["prior"] = ds.target - 0.4
    ds["anomaly"] = ds.temperature - ds.prior
    ds["support"] = np.isfinite(ds.temperature).astype("int8")
    ds["event_mean"] = ds.target - 0.3
    pulse = 1.3 * np.exp(-(((np.arange(len(ds.time)) - 23) / 6) ** 2))
    ds["temperature"] = ds.temperature + pulse[:, None, None, None]
    ds["anomaly"] = ds.temperature - ds.prior
    ds["event_threshold"] = ds.target + 0.4
    ds.attrs.update(
        partition="demo",
        title="Synthetic engineering illustration",
        uncertainty_status="unavailable",
        notice="No satellite measurements, Argo observations or trained model predictions in this fixture",
        model_fingerprint="synthetic-fixture-no-model",
    )
    from .provenance import grid_fingerprint

    ds.attrs["grid_fingerprint"] = grid_fingerprint(ds)
    save_nc(ds, out)
    from .science import score

    rows = [
        {
            "depth": z,
            "model": score(ds.reference.values[:, j], ds.temperature.values[:, j]),
            "climatology": score(ds.reference.values[:, j], ds.prior.values[:, j]),
        }
        for j, z in enumerate(DEPTHS)
    ]
    dump(
        Path(out).with_suffix(".metrics.json"),
        {
            "source": "synthetic",
            "partition": "demo",
            "run_sha256": sha256(out),
            "model_fingerprint": ds.attrs["model_fingerprint"],
            "grid_fingerprint": ds.attrs["grid_fingerprint"],
            "metrics": rows,
            "note": "Computed synthetic illustration; not measured model skill or Argo validation.",
            "matchups": [],
        },
    )


def main():
    p = argparse.ArgumentParser(description="OceanEmbed staged build workflow")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    d = sub.add_parser("demo")
    d.add_argument("--cube", default="data/processed/synthetic.nc")
    d.add_argument("--run", default="demo/runs/demo.nc")
    i = sub.add_parser("inventory")
    i.add_argument("folder")
    i.add_argument("--out", default="data/manifests/inventory.json")
    v = sub.add_parser("validate")
    v.add_argument("cube")
    a = sub.add_parser("prepare")
    a.add_argument("config")
    a.add_argument("--out", default="data/processed/regional.nc")
    t = sub.add_parser("train")
    t.add_argument("config")
    t.add_argument("--resume")
    r = sub.add_parser("predict")
    r.add_argument("cube")
    r.add_argument("bundle")
    r.add_argument("--out", default="demo/runs/model.nc")
    r.add_argument(
        "--partition",
        default="test",
        choices=["train", "validation", "calibration", "test"],
    )
    r.add_argument("--limit", type=int, default=0)
    a = sub.add_parser("argo")
    a.add_argument("pattern")
    a.add_argument("--out", default="data/observations/argo.csv")
    rm = sub.add_parser("rama")
    rm.add_argument("config")
    rm.add_argument("--out", default="data/observations/rama.csv")
    cy = sub.add_parser("cyclone-context")
    cy.add_argument("run")
    cy.add_argument("config")
    cy.add_argument("--out", required=True)
    cw = sub.add_parser("cold-wake")
    cw.add_argument("run")
    cw.add_argument("config")
    cw.add_argument("--depth", type=float, default=50.0)
    cw.add_argument("--days", type=int, default=3)
    cw.add_argument("--out", required=True)
    ps = sub.add_parser("partitions")
    ps.add_argument("argo_csv")
    m = sub.add_parser("match")
    m.add_argument("run")
    m.add_argument("observations")
    m.add_argument("--partition", required=True, choices=["calibration", "test"])
    m.add_argument("--out", required=True)
    rmm = sub.add_parser("rama-match")
    rmm.add_argument("run")
    rmm.add_argument("observations")
    rmm.add_argument("--group", required=True, choices=["development", "held_out"])
    rmm.add_argument("--out", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("matchups")
    c.add_argument("--out", default="artifacts/calibration.json")
    c = sub.add_parser("baseline-select")
    c.add_argument("config")
    c.add_argument("--out", default="artifacts/ridge")
    c = sub.add_parser("baseline-evaluate")
    c.add_argument("config")
    c.add_argument("ridge_dir")
    c.add_argument("--out", default="artifacts/ridge-eval")
    c.add_argument("--partition", default="test", choices=["test"])
    c = sub.add_parser("intervals")
    c.add_argument("run")
    c.add_argument("calibration")
    c.add_argument("test_matchups")
    c.add_argument("--out", required=True)
    c = sub.add_parser("heat-baseline")
    c.add_argument("run")
    c.add_argument("baseline")
    c.add_argument("--out", required=True)
    b = sub.add_parser("bundle")
    b.add_argument("training_dir")
    b.add_argument("--out", default="artifacts/bundle")
    args = p.parse_args()
    if args.cmd == "doctor":
        import importlib.metadata as meta

        print("Python:", sys.version)
        print("Working directory:", Path.cwd())
        for name in ["numpy", "xarray", "fastapi", "gsw", "torch"]:
            try:
                print(name, meta.version(name))
            except meta.PackageNotFoundError:
                print(name, "not installed (torch required for training only)")
        try:
            import torch

            print("CUDA available:", torch.cuda.is_available())
        except ImportError:
            pass
    elif args.cmd == "demo":
        from .demo import create

        create(args.cube)
        demo_run(args.cube, args.run)
        print("Created synthetic demo:", args.run)
    elif args.cmd == "inventory":
        from .prepare import inventory

        print("Files inspected:", len(inventory(args.folder, args.out)))
    elif args.cmd == "validate":
        ds = load_cube(args.cube)
        print(dict(ds.sizes))
        print("Contract passed; source mode:", ds.attrs["source_mode"])
    elif args.cmd == "prepare":
        from .prepare import prepare

        prepare(yaml.safe_load(Path(args.config).read_text()), args.out)
        print(args.out)
    elif args.cmd == "train":
        from .training import train

        train(yaml.safe_load(Path(args.config).read_text()), args.resume)
    elif args.cmd == "predict":
        from .inference import run

        run(
            load_cube(args.cube),
            args.bundle,
            args.out,
            args.partition,
            args.limit,
            cube_path=args.cube,
        )
        print(args.out)
    elif args.cmd == "argo":
        from .observations import argo_to_csv

        print("QC-approved depth records:", argo_to_csv(args.pattern, args.out))
    elif args.cmd == "rama":
        from .rama import rama_to_csv

        print(
            "QC-approved RAMA records:",
            rama_to_csv(yaml.safe_load(Path(args.config).read_text()), args.out),
        )
    elif args.cmd == "cyclone-context":
        from .cyclone import load_track, thermal_context

        track = load_track(yaml.safe_load(Path(args.config).read_text()))
        result = thermal_context(args.run, track, args.out)
        print(
            f"{result['name']}: {result['points_with_thermal_context']}"
            f"/{result['points_total']} track points have thermal context"
        )
        print(args.out)
    elif args.cmd == "cold-wake":
        from .cyclone import load_track, cold_wake

        track = load_track(yaml.safe_load(Path(args.config).read_text()))
        result = cold_wake(args.run, track, args.depth, args.days, args.out)
        print(
            f"{result['name']}: {result['locations_with_complete_windows']}"
            f"/{result['locations_total']} locations have complete windows; "
            f"mean change {result['mean_change_degC']}"
        )
        print(args.out)
    elif args.cmd == "partitions":
        from .observations import partition_summary

        print(json.dumps(partition_summary(args.argo_csv), indent=2))
    elif args.cmd == "match":
        from .observations import match

        match(args.run, args.observations, args.out, args.partition)
        print(args.out)
    elif args.cmd == "rama-match":
        from .rama import match as rama_match

        rama_match(args.run, args.observations, args.out, args.group)
        print(args.out)
    elif args.cmd == "calibrate":
        from .observations import calibrate

        print(calibrate(args.matchups, args.out))
    elif args.cmd == "baseline-select":
        from .baseline import select

        select(yaml.safe_load(Path(args.config).read_text()), args.out)
        print(args.out, "(validation-only; test not read)")
    elif args.cmd == "baseline-evaluate":
        from .baseline import evaluate

        evaluate(
            yaml.safe_load(Path(args.config).read_text()),
            args.ridge_dir,
            args.out,
            args.partition,
        )
        print(args.out)
    elif args.cmd == "intervals":
        from .products import attach_intervals

        attach_intervals(args.run, args.calibration, args.test_matchups, args.out)
    elif args.cmd == "heat-baseline":
        from .products import attach_heat_baseline

        attach_heat_baseline(args.run, args.baseline, args.out)
    elif args.cmd == "bundle":
        source = Path(args.training_dir)
        dest = Path(args.out)
        if dest.exists():
            raise ValueError(
                "Bundle destination already exists; choose a new versioned directory"
            )
        dest.mkdir(parents=True)
        for name in [
            "weights.pt",
            "config.json",
            "transforms.nc",
            "manifest.json",
            "split_manifest.json",
        ]:
            shutil.copy2(source / name, dest / name)
        if (source / "source_manifest.json").exists():
            shutil.copy2(source / "source_manifest.json", dest / "source_manifest.json")
        dump(
            dest / "checksums.json",
            {p.name: sha256(p) for p in dest.iterdir() if p.is_file()},
        )
        print("Inference bundle:", dest)


if __name__ == "__main__":
    main()
