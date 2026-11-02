"""End-to-end tests for cli.py's own argument wiring -- these call main()
with a patched sys.argv, so a broken flag name, a wrong positional order,
or a stale argument (like the old `baseline` command) would fail here
even though the underlying select()/evaluate()/etc. functions are already
covered by their own unit tests."""

import json
import sys
import yaml
import numpy as np
from oceanembed.cli import main


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["oceanembed"] + list(args))
    main()


def test_doctor_runs(monkeypatch, capsys):
    run_cli(monkeypatch, "doctor")
    out = capsys.readouterr().out
    assert "Python" in out


def test_demo_creates_run(tmp_path, monkeypatch):
    cube = tmp_path / "cube.nc"
    run = tmp_path / "run.nc"
    run_cli(monkeypatch, "demo", "--cube", str(cube), "--run", str(run))
    assert cube.exists()
    assert run.exists()
    assert run.with_suffix(".metrics.json").exists()


def test_partitions_command(tmp_path, monkeypatch, capsys):
    import csv

    csv_path = tmp_path / "argo.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["float_id", "profile_id", "date", "lat", "lon", "depth", "temperature", "data_mode"]
        )
        w.writeheader()
        for i in range(100):
            w.writerow(
                {
                    "float_id": f"590{i:04d}", "profile_id": f"590{i:04d}-1-0",
                    "date": "2024-01-01", "lat": 10.0, "lon": 85.0,
                    "depth": 10, "temperature": 28.0, "data_mode": "A",
                }
            )
    run_cli(monkeypatch, "partitions", str(csv_path))
    counts = json.loads(capsys.readouterr().out)
    assert counts["total_floats"] == 100
    assert set(counts) >= {"adaptation", "calibration", "test", "total_floats"}


def test_baseline_select_then_evaluate_via_cli(tmp_path, monkeypatch):
    from oceanembed.demo import create

    cube = tmp_path / "cube.nc"
    create(cube)
    cfg = yaml.safe_load(open("configs/smoke.yaml"))
    cfg["cube"] = str(cube)
    cfg_path = tmp_path / "smoke.yaml"
    cfg_path.write_text(yaml.dump(cfg))

    ridge_dir = tmp_path / "ridge"
    run_cli(monkeypatch, "baseline-select", str(cfg_path), "--out", str(ridge_dir))
    assert (ridge_dir / "selection.json").exists()
    assert not (ridge_dir / "metrics.json").exists()  # select() never writes a report

    eval_dir = tmp_path / "eval"
    run_cli(
        monkeypatch, "baseline-evaluate", str(cfg_path), str(ridge_dir),
        "--out", str(eval_dir), "--partition", "test",
    )
    metrics = json.loads((eval_dir / "metrics.json").read_text())
    assert metrics["stage"] == "evaluate"
    assert metrics["partition"] == "test"


def test_rama_command_via_cli(tmp_path, monkeypatch):
    import xarray as xr
    from oceanembed.contracts import save_nc

    days = 3
    time = np.datetime64("2024-01-01") + np.arange(days)
    ds = xr.Dataset(
        {
            "T_20": (("time",), np.full(days, 28.0), {"units": "degC"}),
            "T_20_QC": (("time",), np.ones(days, dtype=int)),
            "lat_var": ((), 5.0),
            "lon_var": ((), 90.0),
        },
        coords={"time": time},
        attrs={"site_id": "RAMA-1"},
    )
    save_nc(ds, tmp_path / "m1.nc")
    rama_cfg = {
        "reviewed": True,
        "path": str(tmp_path / "*.nc"),
        "mooring_id_attr": "site_id",
        "lat_var": "lat_var",
        "lon_var": "lon_var",
        "depth_variable": {20: "T_20"},
        "qc_variable": {20: "T_20_QC"},
        "accepted_qc": ["1"],
    }
    cfg_path = tmp_path / "rama.yaml"
    cfg_path.write_text(yaml.dump(rama_cfg))
    out_csv = tmp_path / "rama.csv"
    run_cli(monkeypatch, "rama", str(cfg_path), "--out", str(out_csv))
    assert out_csv.exists()
    assert "RAMA-1" in out_csv.read_text()
