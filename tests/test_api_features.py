import csv
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from oceanembed.api import app, dataset
from oceanembed.cli import demo_run
from oceanembed.contracts import dump, sha256
from oceanembed.demo import create


@pytest.fixture
def live(tmp_path, monkeypatch):
    cube = tmp_path / "cube.nc"
    run = tmp_path / "run.nc"
    create(cube)
    demo_run(cube, run)
    monkeypatch.setenv("OCEAN_RUN", str(run))
    dataset.cache_clear()
    yield run, TestClient(app), tmp_path, monkeypatch
    dataset.cache_clear()


def test_field_carries_reliability_states_and_summary(live):
    run, c, *_ = live
    meta = c.get("/runs").json()
    body = c.get(
        "/field", params={"date": meta["dates"][0], "depth": 100}
    ).json()
    assert "reliability" in body
    assert body["reliability_codes"] == {
        "0": "Supported",
        "1": "Caution",
        "2": "Abstain",
    }
    counts = body["reliability_summary"]["counts"]
    assert set(counts) == {"Supported", "Caution", "Abstain"}
    assert sum(counts.values()) == body["reliability_summary"]["total_cells"]
    # Thresholds must travel with the states so a state is auditable.
    assert body["reliability_thresholds"]["states"] == [
        "Supported",
        "Caution",
        "Abstain",
    ]


def test_field_carries_per_cell_reliability_reason(live):
    """/field additionally exposes *why* each cell has its state (e.g. for a
    map tooltip), not only which state it's in. Additive only -- the shape
    must match the state grid and every reason must be a declared one."""
    run, c, *_ = live
    meta = c.get("/runs").json()
    body = c.get(
        "/field", params={"date": meta["dates"][0], "depth": 100}
    ).json()
    reason = body["reliability_reason"]
    state = body["reliability"]
    assert len(reason) == len(state)
    assert all(len(r) == len(s) for r, s in zip(reason, state))
    declared = set(body["reliability_reasons"])
    seen = {code for row in reason for code in row}
    assert seen <= declared
    # A Supported cell's reason must be the "all checks passed" reason, never
    # a stale/edge/unsupported explanation left over from another cell.
    for row_r, row_s in zip(reason, state):
        for r, s in zip(row_r, row_s):
            if s == 0:
                assert r == "ok"


def test_deep_field_abstains_more_than_shallow(live):
    """At 1000 m far more cells are below the seabed than at 0 m, so the
    Abstain count must not decrease with depth."""
    run, c, *_ = live
    date = c.get("/runs").json()["dates"][0]
    shallow = c.get("/field", params={"date": date, "depth": 0}).json()
    deep = c.get("/field", params={"date": date, "depth": 1000}).json()
    assert (
        deep["reliability_summary"]["counts"]["Abstain"]
        >= shallow["reliability_summary"]["counts"]["Abstain"]
    )


def test_profile_carries_reliability_block(live):
    run, c, *_ = live
    date = c.get("/runs").json()["dates"][0]
    body = c.get("/profile", params={"date": date, "lat": 14, "lon": 88}).json()
    r = body["reliability"]
    assert r["overall"] in {"Supported", "Caution", "Abstain"}
    assert r["depths_total"] == 15
    assert len(r["per_depth"]) == 15
    # An uncalibrated demo run must not claim calibrated coverage.
    assert r["calibration_applies"] is False


def test_reanalysis_validation_blocked_on_synthetic_run(live):
    """This is the exact bug this project's own reviewers flagged: a
    synthetic-fixture run's fabricated per-depth RMSE is IDENTICAL at every
    depth (its 'model' temperature is a global sinusoidal offset applied
    uniformly across depth/lat/lon), so displaying it as a real 'Reanalysis'
    evaluation would show a meaningless flat number and look like a real
    result. /validation must refuse it for every source, not only Argo/RAMA."""
    run, c, *_ = live
    body = c.get("/validation", params={"source": "Reanalysis"}).json()
    assert body["metrics"] == []
    assert "synthetic" in body["note"].lower()


def test_reanalysis_validation_still_serves_a_real_run(tmp_path, monkeypatch):
    """The fix above must not accidentally block real runs too."""
    from oceanembed.contracts import dump

    run = tmp_path / "run.nc"
    from oceanembed.demo import create as make_cube
    import xarray as xr
    from oceanembed.contracts import save_nc

    ds = xr.Dataset(
        {"temperature": (("time", "depth", "lat", "lon"), np.full((2, 3, 2, 2), 20.0))},
        coords={
            "time": np.array(["2024-01-01", "2024-01-02"], dtype="datetime64[D]"),
            "depth": [0, 10, 100],
            "lat": [10.0, 11.0],
            "lon": [85.0, 86.0],
        },
        attrs={"source_mode": "research_blended", "partition": "test"},
    )
    save_nc(ds, run)
    metrics = tmp_path / "run.metrics.json"
    dump(
        metrics,
        {
            "source": "Reanalysis",
            "partition": "test",
            "metrics": [{"depth": 0, "model": {"n": 5, "rmse": 0.3}}],
            "note": "real",
        },
    )
    monkeypatch.setenv("OCEAN_RUN", str(run))
    dataset.cache_clear()
    c = TestClient(app)
    body = c.get("/validation", params={"source": "Reanalysis"}).json()
    assert len(body["metrics"]) == 1
    dataset.cache_clear()


def test_baselines_blocked_on_synthetic_cube(tmp_path, monkeypatch):
    """The same fabricated-flat-number risk applies to the ridge/climatology/
    persistence comparison if it was ever computed on a synthetic cube."""
    metrics = tmp_path / "metrics.json"
    dump(
        metrics,
        {
            "stage": "evaluate",
            "partition": "test",
            "source_mode": "synthetic",
            "metrics": [{"depth": 0.0, "ridge": {"rmse": 0.54}}],
        },
    )
    monkeypatch.setenv("OCEAN_BASELINES", str(metrics))
    c = TestClient(app)
    body = c.get("/baselines").json()
    assert body["available"] is False
    assert "synthetic" in body["note"].lower()


def test_runs_reports_freshness_from_real_age_data(live):
    run, c, *_ = live
    body = c.get("/runs").json()
    assert body["freshness"] is not None
    assert body["freshness"]["oldest_input_hours"] >= 0
    assert body["freshness"]["as_of_date"] == body["dates"][-1]


def test_baselines_absent_by_default(live):
    run, c, *_ = live
    body = c.get("/baselines").json()
    assert body["available"] is False
    assert "baseline-evaluate" in body["note"]


def test_baselines_refuses_a_selection_file(live):
    """Selection scores are validation-only; serving them as the frozen
    comparison would publish the number that chose the hyperparameter."""
    run, c, tmp_path, monkeypatch = live
    sel = tmp_path / "selection.json"
    dump(sel, {"stage": "select", "metrics": []})
    monkeypatch.setenv("OCEAN_BASELINES", str(sel))
    assert c.get("/baselines").status_code == 409


def test_baselines_serves_evaluate_output(live):
    run, c, tmp_path, monkeypatch = live
    metrics = tmp_path / "metrics.json"
    dump(
        metrics,
        {
            "stage": "evaluate",
            "partition": "test",
            "metrics": [
                {
                    "depth": 100.0,
                    "ridge": {"n": 10, "rmse": 0.5},
                    "climatology": {"n": 10, "rmse": 0.9},
                    "persistence": {"n": 8, "rmse": 0.7},
                }
            ],
        },
    )
    monkeypatch.setenv("OCEAN_BASELINES", str(metrics))
    body = c.get("/baselines").json()
    assert body["available"] is True
    row = body["metrics"][0]
    assert {"ridge", "climatology", "persistence"} <= set(row)
    # Persistence has its own n and it differs -- the UI must be able to say so.
    assert row["persistence"]["n"] != row["ridge"]["n"]


def test_cyclone_absent_by_default(live):
    run, c, *_ = live
    assert c.get("/cyclone/context").json()["available"] is False
    assert c.get("/cyclone/cold-wake").json()["available"] is False


def test_cyclone_refuses_payload_from_another_run(live):
    run, c, tmp_path, monkeypatch = live
    other = tmp_path / "context.json"
    dump(
        other,
        {
            "source": "cyclone_thermal_context",
            "name": "TESTSTORM",
            "points": [],
            "run_sha256": "0" * 64,
        },
    )
    monkeypatch.setenv("OCEAN_CYCLONE", str(other))
    assert c.get("/cyclone/context").status_code == 409


def test_cyclone_refuses_wrong_payload_type(live):
    run, c, tmp_path, monkeypatch = live
    wrong = tmp_path / "wrong.json"
    dump(wrong, {"source": "cold_wake", "run_sha256": sha256(run)})
    monkeypatch.setenv("OCEAN_CYCLONE", str(wrong))
    assert c.get("/cyclone/context").status_code == 409


def test_cyclone_serves_matching_payload(live):
    run, c, tmp_path, monkeypatch = live
    ctx = tmp_path / "context.json"
    dump(
        ctx,
        {
            "source": "cyclone_thermal_context",
            "name": "TESTSTORM",
            "points": [
                {
                    "datetime": "2024-01-05T00:00:00",
                    "lat": 14.0,
                    "lon": 88.0,
                    "d26_m": 62.0,
                    "tchp_kj_cm2": 44.0,
                }
            ],
            "points_total": 1,
            "points_with_thermal_context": 1,
            "category_scheme": "IMD",
            "run_sha256": sha256(run),
            "limits": "Not an intensity forecast.",
        },
    )
    monkeypatch.setenv("OCEAN_CYCLONE", str(ctx))
    body = c.get("/cyclone/context").json()
    assert body["available"] is True
    assert body["name"] == "TESTSTORM"
    assert body["category_scheme"] == "IMD"
    assert "not an intensity forecast" in body["limits"].lower()
