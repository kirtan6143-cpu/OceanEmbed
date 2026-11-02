"""V2 release-gate regression tests (audit items 1-4, 7, 9)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_demo_artifacts as gate  # noqa: E402

from oceanembed.cli import demo_run  # noqa: E402
from oceanembed.contracts import save_nc  # noqa: E402
from oceanembed.cyclone import cold_wake, thermal_context  # noqa: E402
from oceanembed.demo import create  # noqa: E402
from oceanembed.provenance import grid_fingerprint, inherited_attrs  # noqa: E402

TRACK = {"name": "TEST", "points": [
    {"name": "TEST", "date": "2024-02-20", "lat": 15.0, "lon": 88.0},
    {"name": "TEST", "date": "2024-02-25", "lat": 16.0, "lon": 89.0},
]}


def _synthetic(tmp_path):
    cube, run = tmp_path / "cube.nc", tmp_path / "demo.nc"
    create(cube)
    demo_run(cube, run)
    return run


def _realistic(tmp_path):
    """Synthetic numbers relabelled as a real-mode run so every gate is exercised."""
    run = _synthetic(tmp_path)
    with xr.open_dataset(run) as f:
        ds = f.load()
    ds.attrs.update(source_mode="research_blended", partition="test",
                    surface_convention="copy_shallowest_to_zero", model_fingerprint="m" * 64)
    for v in ("temperature", "anomaly"):
        ds[v].loc[dict(depth=1000.0)] = np.nan
    ds["support"].loc[dict(depth=1000.0)] = 0
    save_nc(ds, run)
    run_sha = gate.sha256(run)
    metrics = json.loads((tmp_path / "demo.metrics.json").read_text())
    metrics.update(run_sha256=run_sha, source="GLORYS teacher",
                   model_fingerprint=ds.attrs["model_fingerprint"], grid_fingerprint=ds.attrs["grid_fingerprint"])
    (tmp_path / "demo.metrics.json").write_text(json.dumps(metrics))
    argo = {"source": "Argo", "partition": "test", "run_sha256": run_sha,
            "model_fingerprint": ds.attrs["model_fingerprint"],
            "matchups": [{"depth": 0.0, "observed": 28.0, "predicted": 28.1}],
            "metrics": [{"depth": 0, "model": {"rmse": 0.1}}]}
    (tmp_path / "argo_validation.json").write_text(json.dumps(argo))
    thermal_context(run, TRACK, tmp_path / "cyclone_context.json")
    cold_wake(run, TRACK, 50.0, 3, tmp_path / "cold_wake.json")
    return run


def test_synthetic_run_never_passes_strict_gate(tmp_path):
    failures, _, _ = gate.verify(_synthetic(tmp_path))
    assert any("synthetic fixture" in f for f in failures)


def test_synthetic_metrics_are_sha_and_fingerprint_bound(tmp_path):
    run = _synthetic(tmp_path)
    metrics = json.loads((tmp_path / "demo.metrics.json").read_text())
    assert metrics["run_sha256"] == gate.sha256(run)
    with xr.open_dataset(run) as ds:
        assert metrics["grid_fingerprint"] == ds.attrs["grid_fingerprint"]


def test_complete_realistic_release_passes(tmp_path):
    failures, warnings, info = gate.verify(_realistic(tmp_path))
    assert failures == [], failures
    assert set(info["artifacts"]) == set(gate.ARTIFACTS)


def test_manifest_records_every_artifact_hash(tmp_path):
    run = _realistic(tmp_path)
    assert gate.main([str(run), "--manifest", str(tmp_path / "m.json")]) == 0
    m = json.loads((tmp_path / "m.json").read_text())
    assert m["verdict"] == "PASS" and m["scientific_release"] is True
    assert m["run"]["sha256"] == gate.sha256(run)
    assert set(m["artifacts"]) == set(gate.ARTIFACTS)
    assert m["run_identity"]["grid_fingerprint"]


@pytest.mark.parametrize("name", gate.ARTIFACTS)
def test_stale_artifact_from_another_run_is_rejected(tmp_path, name):
    run = _realistic(tmp_path)
    obj = json.loads((tmp_path / name).read_text())
    obj["run_sha256"] = "0" * 64
    (tmp_path / name).write_text(json.dumps(obj))
    failures, _, _ = gate.verify(run)
    assert any(name in f and "run_sha256" in f for f in failures)


def test_removed_cyclone_surface_workaround_is_rejected(tmp_path):
    run = _realistic(tmp_path)
    obj = json.loads((tmp_path / "cyclone_context.json").read_text())
    obj["points_with_estimated_surface"] = 3
    (tmp_path / "cyclone_context.json").write_text(json.dumps(obj))
    assert any("5 m surface workaround" in f for f in gate.verify(run)[0])


def test_native_1000m_values_are_rejected(tmp_path):
    run = _realistic(tmp_path)
    with xr.open_dataset(run) as f:
        ds = f.load()
    ds["support"].loc[dict(depth=1000.0)] = 1
    save_nc(ds, run)
    assert any("1000 m has native support" in f for f in gate.verify(run)[0])


def test_model_fingerprint_mismatch_is_rejected(tmp_path):
    run = _realistic(tmp_path)
    obj = json.loads((tmp_path / "argo_validation.json").read_text())
    obj["model_fingerprint"] = "x" * 64
    (tmp_path / "argo_validation.json").write_text(json.dumps(obj))
    assert any("model_fingerprint" in f for f in gate.verify(run)[0])


def test_missing_surface_convention_is_rejected(tmp_path):
    run = _realistic(tmp_path)
    with xr.open_dataset(run) as f:
        ds = f.load()
    del ds.attrs["surface_convention"]
    save_nc(ds, run)
    assert any("surface_convention" in f for f in gate.verify(run)[0])


def test_grid_fingerprint_is_stable_and_grid_sensitive(tmp_path):
    run = _synthetic(tmp_path)
    with xr.open_dataset(run) as f:
        ds = f.load()
    assert grid_fingerprint(ds) == grid_fingerprint(ds.copy())
    assert grid_fingerprint(ds) != grid_fingerprint(ds.assign_coords(lat=ds.lat + 0.25))


def test_inference_inherits_cube_surface_metadata():
    attrs = {"surface_convention": "copy_shallowest_to_zero", "surface_tolerance_m": 1.0,
             "temperature_convention": "in_situ_degC", "unrelated": 1}
    assert inherited_attrs(attrs) == {k: attrs[k] for k in
                                      ("surface_convention", "surface_tolerance_m", "temperature_convention")}
