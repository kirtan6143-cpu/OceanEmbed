import csv
import json
import sys

import numpy as np
import xarray as xr
import yaml

from oceanembed.cli import main
from oceanembed.contracts import DEPTHS, save_nc


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["oceanembed"] + list(args))
    main()


def _track_csv(path):
    rows = [
        {"N": "TESTSTORM", "T": "2024-01-05", "LA": "14.0", "LO": "88.0"},
        {"N": "TESTSTORM", "T": "2024-01-06", "LA": "14.5", "LO": "88.5"},
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["N", "T", "LA", "LO"])
        w.writeheader()
        w.writerows(rows)
    return path


def _run_nc(path):
    time = np.datetime64("2024-01-01") + np.arange(20)
    values = np.full((20, len(DEPTHS), 5, 5), 20.0)
    ds = xr.Dataset(
        {"temperature": (("time", "depth", "lat", "lon"), values)},
        coords={
            "time": time,
            "depth": DEPTHS,
            "lat": np.linspace(10, 18, 5),
            "lon": np.linspace(84, 92, 5),
        },
        attrs={"source_mode": "research_blended"},
    )
    save_nc(ds, path)
    return path


def test_cyclone_context_via_cli(tmp_path, monkeypatch):
    cfg = {
        "reviewed": True,
        "path": str(_track_csv(tmp_path / "t.csv")),
        "columns": {"name": "N", "datetime": "T", "lat": "LA", "lon": "LO"},
        "source": "test",
    }
    cfg_path = tmp_path / "cyclone.yaml"
    cfg_path.write_text(yaml.dump(cfg))
    run = _run_nc(tmp_path / "run.nc")
    out = tmp_path / "context.json"
    run_cli(monkeypatch, "cyclone-context", str(run), str(cfg_path), "--out", str(out))
    result = json.loads(out.read_text())
    assert result["source"] == "cyclone_thermal_context"
    assert result["points_total"] == 2


def test_cold_wake_via_cli(tmp_path, monkeypatch):
    cfg = {
        "reviewed": True,
        "path": str(_track_csv(tmp_path / "t.csv")),
        "columns": {"name": "N", "datetime": "T", "lat": "LA", "lon": "LO"},
        "source": "test",
    }
    cfg_path = tmp_path / "cyclone.yaml"
    cfg_path.write_text(yaml.dump(cfg))
    run = _run_nc(tmp_path / "run.nc")
    out = tmp_path / "wake.json"
    run_cli(
        monkeypatch,
        "cold-wake",
        str(run),
        str(cfg_path),
        "--depth",
        "50",
        "--days",
        "2",
        "--out",
        str(out),
    )
    result = json.loads(out.read_text())
    assert result["source"] == "cold_wake"
    assert result["depth"] == 50.0
    assert result["window_days"] == 2
