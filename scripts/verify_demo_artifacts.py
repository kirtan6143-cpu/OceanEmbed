"""V2 release gate: verify that every artifact belongs to the exact demo.nc served.

Checks the NetCDF contract (depths, channels, 0 m support, 1000 m non-support,
surface-convention metadata, run fingerprints) and the SHA-256 / fingerprint
binding of every dependent artifact (Argo, cyclone-context, cold-wake, metrics).
It never alters scientific data. With --manifest it writes a release manifest
recording every artifact hash, the run identity and the software environment.

Exit code 0 = PASS, 1 = FAIL.

    python scripts/verify_demo_artifacts.py demo/runs/demo.nc --manifest demo/runs/RELEASE_MANIFEST.json

Synthetic fixtures always FAIL unless --allow-synthetic is given (pipeline
rehearsal only; a synthetic PASS is never scientific evidence).
"""
import argparse
import datetime
import hashlib
import importlib.metadata as meta
import json
import platform
import sys
from pathlib import Path

import numpy as np
import xarray as xr

DEPTHS = [0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 700, 1000]
CHANNELS = ["sst", "sla", "current_u", "current_v", "wind_u", "wind_v", "sss"]
ARTIFACTS = ["argo_validation.json", "cyclone_context.json", "cold_wake.json", "demo.metrics.json"]
REQUIRED_ATTRS = ["source_mode", "surface_convention", "model_fingerprint", "grid_fingerprint"]
ACCEPTED_SURFACE = {"copy_shallowest_to_zero", "synthetic exact zero depth"}
ENV_PACKAGES = ["numpy", "scipy", "xarray", "h5netcdf", "h5py", "gsw", "fastapi", "pydantic", "torch"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def environment():
    versions = {}
    for name in ENV_PACKAGES:
        try:
            versions[name] = meta.version(name)
        except meta.PackageNotFoundError:
            versions[name] = None
    return {"python": sys.version.split()[0], "platform": platform.platform(), "packages": versions}


def verify(run: Path, root: Path | None = None, allow_synthetic: bool = False):
    """Return (failures, warnings, info). Pure function: nothing is written."""
    run = Path(run)
    root = Path(root) if root else run.parent
    failures, warnings = [], []
    info = {"run": str(run), "run_sha256": sha256(run), "attrs": {}, "artifacts": {}}
    expected = info["run_sha256"]
    attrs = {}

    try:
        with xr.open_dataset(run) as f:
            ds = f.load()
        attrs = dict(ds.attrs)
        info["attrs"] = {k: (v.item() if hasattr(v, "item") else v) for k, v in attrs.items()
                         if isinstance(v, (str, int, float, np.generic))}
        for var in ("temperature", "anomaly", "support", "prior"):
            if var not in ds:
                failures.append(f"demo.nc missing {var}")
        if "depth" not in ds.coords:
            failures.append("demo.nc missing depth coordinate")
        elif [float(v) for v in ds.depth.values] != [float(v) for v in DEPTHS]:
            failures.append(f"demo.nc depth grid mismatch: {[float(v) for v in ds.depth.values]}")
        if "channel" not in ds.coords:
            failures.append("demo.nc missing channel coordinate")
        elif [str(v) for v in ds.channel.values] != CHANNELS:
            failures.append(f"demo.nc channel order mismatch: {[str(v) for v in ds.channel.values]}")

        depth_ok = "depth" in ds.coords and 0.0 in [float(v) for v in ds.depth.values]
        if "temperature" in ds and depth_ok:
            finite0 = int(np.isfinite(ds.temperature.sel(depth=0.0).values).sum())
            info["finite_0m_cells"] = finite0
            if finite0 <= 0:
                failures.append("demo.nc has zero finite temperature cells at 0 m")
            if "support" in ds:
                support0 = int(np.count_nonzero(ds.support.sel(depth=0.0).values))
                info["support_0m_cells"] = support0
                if support0 <= 0:
                    failures.append("demo.nc has zero support cells at 0 m")
                s1000 = int(np.count_nonzero(ds.support.sel(depth=1000.0).values))
                t1000 = int(np.isfinite(ds.temperature.sel(depth=1000.0).values).sum())
                info["support_1000m_cells"] = s1000
                synthetic_run = attrs.get("source_mode") == "synthetic"
                if (s1000 or t1000) and not synthetic_run:
                    failures.append(
                        "1000 m has native support/values; the V2 source support ends ~902 m, "
                        "so 1000 m must stay unsupported (display estimate only)"
                    )

        for key in REQUIRED_ATTRS:
            if attrs.get(key) in (None, ""):
                failures.append(f"demo.nc missing attribute {key}")
        sc = attrs.get("surface_convention")
        if sc is not None and sc not in ACCEPTED_SURFACE:
            failures.append(f"demo.nc surface_convention {sc!r} does not produce a supported 0 m level")
        if attrs.get("source_mode") == "synthetic" or attrs.get("partition") == "demo":
            (warnings if allow_synthetic else failures).append(
                "demo.nc is a synthetic fixture; it can rehearse the pipeline but is not a scientific release"
            )
    except Exception as exc:  # noqa: BLE001 - reported as a gate failure
        failures.append(f"unable to inspect demo.nc: {type(exc).__name__}: {exc}")

    def load(name, required=True):
        path = root / name
        if not path.exists():
            (failures if required else warnings).append(f"missing {name}")
            return None
        info["artifacts"][name] = {"path": str(path), "sha256": sha256(path)}
        try:
            obj = json.loads(path.read_text(encoding="utf8"))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"invalid {name}: {exc}")
            return None
        if obj.get("run_sha256") != expected:
            failures.append(f"{name} run_sha256 does not match demo.nc")
        return obj

    synthetic_rehearsal = allow_synthetic and attrs.get("source_mode") == "synthetic"

    argo = load("argo_validation.json", required=not synthetic_rehearsal)
    if argo is not None:
        if argo.get("source") != "Argo":
            failures.append("argo_validation.json source must be 'Argo'")
        if argo.get("partition") != "test":
            failures.append("argo_validation.json must be the held-out 'test' partition")
        if argo.get("model_fingerprint") != attrs.get("model_fingerprint"):
            failures.append("argo_validation.json model_fingerprint does not match demo.nc")
        depths = {float(r["depth"]) for r in argo.get("matchups", []) if r.get("depth") is not None}
        info["argo_matchups"] = len(argo.get("matchups", []))
        if 0.0 not in depths:
            warnings.append("Argo artifact has no 0 m matchup (acceptable only if no 0 m Argo records exist)")
        if 1000.0 in depths:
            failures.append("argo_validation.json contains 1000 m matchups; 1000 m is not natively supported")
        metrics = argo.get("metrics", [])
        if not metrics or any("model" not in row for row in metrics):
            failures.append("argo_validation.json metrics must use nested model metrics")

    cyclone = load("cyclone_context.json")
    if cyclone is not None:
        text = json.dumps(cyclone)
        if "surface_estimated" in text or "points_with_estimated_surface" in cyclone or "surface_note" in cyclone:
            failures.append("cyclone_context.json still contains the removed 5 m surface workaround")
        if cyclone.get("source") != "cyclone_thermal_context":
            failures.append("cyclone_context.json has an unexpected source")

    cold = load("cold_wake.json")
    if cold is not None:
        for key in ("depth", "window_days", "limits", "records"):
            if key not in cold:
                failures.append(f"cold_wake.json missing methodology field {key}")

    metrics = load("demo.metrics.json")
    if metrics is not None:
        if len(metrics.get("metrics", [])) != len(DEPTHS):
            failures.append("demo.metrics.json must contain exactly 15 canonical depth entries")
        for key in ("model_fingerprint", "grid_fingerprint"):
            if metrics.get(key) != attrs.get(key):
                failures.append(f"demo.metrics.json {key} does not match demo.nc")
        if metrics.get("source") != "synthetic":
            warnings.append("demo.metrics.json is teacher/reference evaluation, not independent observational validation")

    return failures, warnings, info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--artifacts", type=Path, default=None)
    ap.add_argument("--manifest", type=Path, default=None, help="write a release manifest JSON")
    ap.add_argument("--allow-synthetic", action="store_true", help="pipeline rehearsal only")
    args = ap.parse_args(argv)

    failures, warnings, info = verify(args.run, args.artifacts, args.allow_synthetic)
    print(f"run: {info['run']}")
    print(f"run_sha256: {info['run_sha256']}")
    for key in ("finite_0m_cells", "support_0m_cells", "support_1000m_cells", "argo_matchups"):
        if key in info:
            print(f"{key}: {info[key]}")
    verdict = "FAIL" if failures else "PASS"
    print(f"\n{verdict}")
    for item in failures:
        print("-", item)
    for item in warnings:
        print("WARNING:", item)

    if args.manifest:
        manifest = {
            "verdict": verdict,
            "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "scientific_release": verdict == "PASS" and not args.allow_synthetic,
            "run": {"path": info["run"], "sha256": info["run_sha256"]},
            "run_identity": {k: info["attrs"].get(k) for k in (
                "source_mode", "partition", "model_fingerprint", "grid_fingerprint",
                "source_cube_sha256", "split_manifest_sha256", "inference_config_fingerprint",
                "weights_sha256", "surface_convention", "surface_tolerance_m")},
            "artifacts": info["artifacts"],
            "failures": failures,
            "warnings": warnings,
            "environment": environment(),
        }
        args.manifest.write_text(json.dumps(manifest, indent=2, default=str))
        print(f"manifest: {args.manifest}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
