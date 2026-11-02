import numpy as np
import pytest
import xarray as xr
from oceanembed.contracts import dump, sha256, save_nc
from oceanembed.observations import PARTITION_SCHEME_VERSION
from oceanembed.products import attach_intervals, attach_heat_baseline


def test_interval_lineage_and_scope(tmp_path):
    ds = xr.Dataset(
        {"temperature": (("time", "depth", "lat", "lon"), np.ones((2, 3, 1, 1)) * 20)},
        coords={
            "time": np.array(["2024-01-01", "2024-01-02"], dtype="datetime64[D]"),
            "depth": [0, 10, 100],
            "lat": [10.0],
            "lon": [85.0],
        },
        attrs={"source_mode": "research_blended", "partition": "test", "model_fingerprint": "fixture-model"},
    )
    run = tmp_path / "run.nc"
    save_nc(ds, run)
    cal = {
        "float_ids": ["cal-float"],
        "last_date": "2023-12-01",
        "depths": [10, 100],
        "model_fingerprint": "fixture-model",
        "partition_fingerprint": "fixture-split",
        "q_degC": 1.0,
        "alpha": 0.1,
        "partition_scheme_version": PARTITION_SCHEME_VERSION,
    }
    test = {
        "model_fingerprint": "fixture-model",
        "partition_fingerprint": "fixture-split",
        "source": "Argo",
        "partition": "test",
        "float_ids": ["test-float"],
        "run_sha256": sha256(run),
        "partition_scheme_version": PARTITION_SCHEME_VERSION,
        "matchups": [
            {
                "date": "2024-01-01",
                "profile_id": "test-profile",
                "depth": z,
                "predicted": 20.0,
                "observed": 20.5,
            }
            for z in [10, 100]
        ],
    }
    dump(tmp_path / "cal.json", cal)
    dump(tmp_path / "test.json", test)
    out = tmp_path / "out.nc"
    attach_intervals(run, tmp_path / "cal.json", tmp_path / "test.json", out)
    with xr.open_dataset(out) as f:
        assert f.lower.sel(depth=0).isnull().all()
        assert (f.lower.sel(depth=100) == 19).all()
        assert f.attrs["base_run_sha256"] == sha256(run)
    test["float_ids"] = ["cal-float"]
    dump(tmp_path / "test.json", test)
    with pytest.raises(ValueError, match="overlap"):
        attach_intervals(run, tmp_path / "cal.json", tmp_path / "test.json", out)


def test_interval_rejects_stale_partition_scheme(tmp_path):
    ds = xr.Dataset(
        {"temperature": (("time", "depth", "lat", "lon"), np.ones((2, 3, 1, 1)) * 20)},
        coords={
            "time": np.array(["2024-01-01", "2024-01-02"], dtype="datetime64[D]"),
            "depth": [0, 10, 100],
            "lat": [10.0],
            "lon": [85.0],
        },
        attrs={"source_mode": "research_blended", "partition": "test"},
    )
    run = tmp_path / "run.nc"
    save_nc(ds, run)
    cal = {
        "float_ids": ["cal-float"],
        "last_date": "2023-12-01",
        "depths": [10, 100],
        "q_degC": 1.0,
        "alpha": 0.1,
        "partition_scheme_version": PARTITION_SCHEME_VERSION - 1,  # stale on purpose
    }
    test = {
        "source": "Argo",
        "partition": "test",
        "float_ids": ["test-float"],
        "run_sha256": sha256(run),
        "partition_scheme_version": PARTITION_SCHEME_VERSION,
        "matchups": [
            {"date": "2024-01-01", "profile_id": "test-profile", "depth": z,
             "predicted": 20.0, "observed": 20.5}
            for z in [10, 100]
        ],
    }
    dump(tmp_path / "cal.json", cal)
    dump(tmp_path / "test.json", test)
    with pytest.raises(ValueError, match="partition scheme"):
        attach_intervals(run, tmp_path / "cal.json", tmp_path / "test.json", tmp_path / "out.nc")


def test_calendar_baseline_attachment(tmp_path):
    ds = xr.Dataset(
        {"temperature": (("time", "depth", "lat", "lon"), np.ones((2, 1, 1, 1)) * 28)},
        coords={
            "time": np.array(["2024-02-28", "2024-02-29"], dtype="datetime64[D]"),
            "depth": [0],
            "lat": [10.0],
            "lon": [85.0],
        },
    )
    save_nc(ds, tmp_path / "run.nc")
    b = xr.Dataset(
        {
            v: (
                ("month_day", "depth", "lat", "lon"),
                np.ones((2, 1, 1, 1)) * x,
                {"units": "degC"},
            )
            for v, x in [("event_mean", 26), ("event_threshold", 27)]
        },
        coords={
            "month_day": ["02-28", "02-29"],
            "depth": [0],
            "lat": [10.0],
            "lon": [85.0],
        },
        attrs={
            "source": "constructed test fixture",
            "baseline_period": "test-only",
            "method": "fixture",
            "leap_day_policy": "explicit",
        },
    )
    save_nc(b, tmp_path / "baseline.nc")
    attach_heat_baseline(
        tmp_path / "run.nc", tmp_path / "baseline.nc", tmp_path / "out.nc"
    )
    with xr.open_dataset(tmp_path / "out.nc") as f:
        assert (f.event_threshold == 27).all()
