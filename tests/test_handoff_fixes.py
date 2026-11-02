import numpy as np
import pytest
import xarray as xr

from oceanembed.contracts import DEPTHS, CHANNELS, save_nc, load_cube
from oceanembed.prepare import prepare


def _cfg(tmp_path, first_depth, surface_convention="copy_shallowest_to_zero"):
    time = np.arange("2021-01-01", "2021-01-03", dtype="datetime64[D]")
    lat = [10.0]
    lon = [85.0]
    raw = xr.Dataset(coords={"time": time, "lat": lat, "lon": lon})
    for c in CHANNELS:
        raw[c] = (("time", "lat", "lon"), np.ones((2, 1, 1)), {"units": "native"})
    raw["age"] = (("time", "lat", "lon"), np.ones((2, 1, 1)), {"units": "hours"})
    raw["qc"] = (("time", "lat", "lon"), np.ones((2, 1, 1), dtype=int), {})
    raw_path = tmp_path / "raw.nc"
    save_nc(raw, raw_path)

    z = np.array([first_depth, 10.0, 50.0, 100.0, 300.0, 700.0, 1100.0])
    target = xr.Dataset(coords={"time": time, "depth": z, "lat": lat, "lon": lon})
    target["thetao"] = (("time", "depth", "lat", "lon"), np.full((2, len(z), 1, 1), 20.0), {"units": "degrees_C"})
    target["so"] = (("time", "depth", "lat", "lon"), np.full((2, len(z), 1, 1), 35.0), {"units": "1e-3"})
    target_path = tmp_path / "target.nc"
    save_nc(target, target_path)

    bath = xr.Dataset({"depth_m": (("lat", "lon"), np.full((1, 1), 1500.0))}, coords={"lat": lat, "lon": lon})
    bath_path = tmp_path / "bath.nc"
    save_nc(bath, bath_path)

    channels = {
        c: {
            "path": str(raw_path), "variable": c, "source_units": "native",
            "qc_variable": "qc", "accepted_qc": [1], "age_variable": "age",
            "spatial_tolerance_deg": 0.1,
        } for c in CHANNELS
    }
    return {
        "reviewed": True, "mode": "research_blended", "start": "2021-01-01", "end": "2021-01-02",
        "lat": [10, 10], "lon": [85, 85], "step": 0.25,
        "channels": channels,
        "target": {
            "path": str(target_path), "temperature": "thetao", "salinity": "so",
            "temperature_units": "degrees_C", "salinity_units": "1e-3", "convention": "potential",
            "surface_convention": surface_convention, "spatial_tolerance_deg": 0.1,
        },
        "bathymetry": {"path": str(bath_path), "variable": "depth_m", "spatial_tolerance_deg": 0.1},
    }


def test_surface_tolerance_accepts_submetre_source_level(tmp_path):
    out = tmp_path / "cube.nc"
    prepare(_cfg(tmp_path, 0.494025), out)
    ds = load_cube(out)
    assert np.isfinite(ds.target.sel(depth=0).values).all()
    # The 0 m level is a copy of the shallowest source level (0.494 m) after the
    # potential -> in-situ conversion at that level's pressure. It must NOT be
    # bit-identical to 5 m: in-situ temperature rises adiabatically with pressure,
    # so 5 m is ~1e-3 degC warmer for a uniform potential-temperature column.
    # (V2's original assertion compared 0 m with 5 m at 1e-5 and failed once gsw
    # was installed and the test actually ran.)
    import gsw
    p0 = gsw.p_from_z(-0.494025, 10.0)
    sa0 = gsw.SA_from_SP(35.0, p0, 85.0, 10.0)
    expected0 = gsw.t_from_CT(sa0, gsw.CT_from_pt(sa0, 20.0), p0)
    np.testing.assert_allclose(ds.target.sel(depth=0).values, expected0, atol=1e-4)
    diff = ds.target.sel(depth=5).values - ds.target.sel(depth=0).values
    assert (diff >= 0).all() and (diff < 0.01).all()


def test_surface_copy_is_recorded_in_cube_metadata(tmp_path):
    out = tmp_path / "cube.nc"
    prepare(_cfg(tmp_path, 0.494025), out)
    ds = load_cube(out)
    assert ds.attrs["surface_convention"] == "copy_shallowest_to_zero"
    assert float(ds.attrs["surface_tolerance_m"]) == 1.0


def test_surface_tolerance_does_not_extrapolate_material_gap(tmp_path):
    out = tmp_path / "cube.nc"
    prepare(_cfg(tmp_path, 2.0), out)
    ds = load_cube(out)
    assert np.isnan(ds.target.sel(depth=0).values).all()


def test_surface_copy_requires_explicit_convention(tmp_path):
    out = tmp_path / "cube.nc"
    prepare(_cfg(tmp_path, 0.494025, surface_convention="no_extrapolation"), out)
    ds = load_cube(out)
    assert np.isnan(ds.target.sel(depth=0).values).all()


def test_1000m_estimate_preserves_requested_variable_and_semantics(tmp_path, monkeypatch):
    from oceanembed.demo import create
    from oceanembed.cli import demo_run
    from oceanembed.api import app, dataset
    from fastapi.testclient import TestClient

    cube = tmp_path / "cube.nc"
    run = tmp_path / "run.nc"
    create(cube)
    demo_run(cube, run)
    monkeypatch.setenv("OCEAN_RUN", str(run))
    dataset.cache_clear()
    c = TestClient(app)
    date = c.get("/runs").json()["dates"][0]

    temp700 = c.get("/field", params={"date": date, "depth": 700, "var": "temperature"}).json()
    anomaly700 = c.get("/field", params={"date": date, "depth": 700, "var": "anomaly"}).json()
    temp1000 = c.get("/field", params={"date": date, "depth": 1000, "var": "temperature"}).json()
    anomaly1000 = c.get("/field", params={"date": date, "depth": 1000, "var": "anomaly"}).json()

    assert temp1000["depth_status"] == "display_estimate"
    assert anomaly1000["depth_status"] == "display_estimate"
    assert temp1000["estimate_source_depth"] == 700.0
    assert anomaly1000["estimate_source_depth"] == 700.0
    assert temp1000["reliability_applies_to_display"] is False
    assert anomaly1000["reliability_applies_to_display"] is False
    np.testing.assert_allclose(
        np.asarray(temp1000["estimated_z"], dtype=float),
        np.asarray(temp700["z"], dtype=float),
        equal_nan=True,
    )
    np.testing.assert_allclose(
        np.asarray(anomaly1000["estimated_z"], dtype=float),
        np.asarray(anomaly700["z"], dtype=float),
        equal_nan=True,
    )
    dataset.cache_clear()
