"""Attach explicitly sourced product metadata; never infer a climate baseline from test data."""

import json
from pathlib import Path
import numpy as np
import xarray as xr
from .contracts import save_nc, sha256, dump
from .observations import PARTITION_SCHEME_VERSION


def attach_intervals(run_path, cal_path, test_path, out):
    cal = json.loads(Path(cal_path).read_text())
    test = json.loads(Path(test_path).read_text())
    if test.get("source") != "Argo" or test.get("partition") != "test":
        raise ValueError("Final Argo test matchups required")
    for label, obj in [("calibration", cal), ("test", test)]:
        if obj.get("partition_scheme_version") != PARTITION_SCHEME_VERSION:
            raise ValueError(
                f"{label} matchups were produced under a different "
                f"float-partition scheme (expected version "
                f"{PARTITION_SCHEME_VERSION}). Regenerate both calibration "
                "and test matchups with the current match()/calibrate() "
                "before attaching intervals -- mixing schemes can assign a "
                "float to test today when it was calibration under the old "
                "scheme, or vice versa."
            )
    for key in ["model_fingerprint", "partition_fingerprint"]:
        if not cal.get(key) or cal[key] != test.get(key):
            raise ValueError(f"Calibration/test {key} differs; regenerate matching artifacts")
    if set(cal["float_ids"]) & set(test["float_ids"]):
        raise ValueError("Calibration and test floats overlap")
    if min(r["date"] for r in test["matchups"]) <= cal["last_date"]:
        raise ValueError("Test must follow calibration chronologically")
    if test["run_sha256"] != sha256(run_path):
        raise ValueError("Matchups belong to a different run")
    with xr.open_dataset(run_path) as f:
        ds = f.load()
    if ds.attrs.get("source_mode") == "synthetic":
        raise ValueError("No empirical intervals on a synthetic run")
    if ds.attrs.get("model_fingerprint") != cal["model_fingerprint"]:
        raise ValueError("Run and calibrated model differ")
    depths = cal["depths"]
    q = float(cal["q_degC"])
    if not np.isfinite(q) or q < 0 or not 0 < cal["alpha"] < 1:
        raise ValueError("Invalid calibration quantile or alpha")
    profiles = {}
    for r in test["matchups"]:
        profiles.setdefault(r["profile_id"], {})[r["depth"]] = abs(
            r["predicted"] - r["observed"]
        )
    rows = np.array([[r.get(z, np.nan) for z in depths] for r in profiles.values()])
    rows = rows[np.isfinite(rows).all(axis=1)]
    if not len(rows):
        raise ValueError("No complete test profiles for interval audit")
    audit = {
        "n_profiles": len(rows),
        "simultaneous_coverage": float(np.mean(np.max(rows, axis=1) <= q)),
        "target_coverage": 1 - cal["alpha"],
        "q_degC": q,
        "depths": depths,
        "note": "Descriptive held-out coverage, not a guarantee under dependence or distribution shift. No retuning on test.",
    }
    supported = ds.depth.isin(depths)
    ds["lower"] = (ds.temperature - q).where(supported)
    ds["upper"] = (ds.temperature + q).where(supported)
    ds.attrs.update(
        uncertainty_status="Empirical constant-width profile interval; inspect coverage audit",
        interval_audit=json.dumps(audit),
        calibration_sha256=sha256(cal_path),
        base_run_sha256=ds.attrs.get("base_run_sha256", sha256(run_path)),
    )
    save_nc(ds, out)
    dump(Path(out).with_suffix(".coverage.json"), audit)


def attach_heat_baseline(run_path, baseline_path, out):
    with xr.open_dataset(run_path) as f:
        ds = f.load()
    with xr.open_dataset(baseline_path) as f:
        b = f.load()
    for key in ["baseline_period", "source", "method", "leap_day_policy"]:
        if not b.attrs.get(key):
            raise ValueError(f"Baseline metadata missing: {key}")
    for c in ["depth", "lat", "lon"]:
        if not np.array_equal(ds[c], b[c]):
            raise ValueError(f"Baseline grid differs: {c}")
    for v in ["event_mean", "event_threshold"]:
        if (
            v not in b
            or b[v].dims != ("month_day", "depth", "lat", "lon")
            or b[v].attrs.get("units") != "degC"
        ):
            raise ValueError(
                f"{v} must have month_day/depth/lat/lon dimensions and degC units"
            )
        keys = ds.time.dt.strftime("%m-%d").values
        if not set(keys) <= set(b.month_day.values):
            raise ValueError("Baseline lacks a required calendar day")
        arr = (
            b[v]
            .sel(month_day=xr.DataArray(keys, dims="time"))
            .drop_vars("month_day")
            .assign_coords(time=ds.time)
        )
        ds[v] = arr
    finite = np.isfinite(ds.event_mean) & np.isfinite(ds.event_threshold)
    if bool(((ds.event_threshold <= ds.event_mean) & finite).any()):
        raise ValueError("Threshold must exceed mean wherever both exist")
    ds.attrs.update(
        heat_baseline=json.dumps(dict(b.attrs)),
        heat_baseline_sha256=sha256(baseline_path),
        base_run_sha256=ds.attrs.get("base_run_sha256", sha256(run_path)),
    )
    save_nc(ds, out)
