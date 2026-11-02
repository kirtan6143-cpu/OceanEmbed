import copy
import numpy as np
import pytest
import xarray as xr
from oceanembed.contracts import CHANNELS, DEPTHS, save_nc, load_cube
from oceanembed.prepare import prepare


def test_native_preparation_and_qc(tmp_path):
    time = np.arange("2021-01-01", "2021-01-04", dtype="datetime64[D]")
    lat = [10.0, 10.25]
    lon = [85.0, 85.25]
    shape = (3, 2, 2)
    raw = xr.Dataset(coords={"time": time, "lat": lat, "lon": lon})
    for j, c in enumerate(CHANNELS):
        raw[c] = (
            ("time", "lat", "lon"),
            np.full(shape, 20.0 if c == "sst" else 1.0),
            {"units": "native"},
        )
    raw["age"] = (("time", "lat", "lon"), np.ones(shape) * 12, {"units": "hours"})
    raw["qc"] = (("time", "lat", "lon"), np.ones(shape, dtype=int))
    raw.qc.values[0, 0, 0] = 4
    save_nc(raw, tmp_path / "input.nc")
    z = np.array([1, 10, 50, 100, 300, 700, 1100.0])
    target = xr.Dataset(coords={"time": time, "depth": z, "lat": lat, "lon": lon})
    target["thetao"] = (
        ("time", "depth", "lat", "lon"),
        np.full((3, 7, 2, 2), 20.0),
        {"units": "degrees_C"},
    )
    target["so"] = (
        ("time", "depth", "lat", "lon"),
        np.full((3, 7, 2, 2), 35.0),
        {"units": "1e-3"},
    )
    save_nc(target, tmp_path / "target.nc")
    bath = xr.Dataset(
        {"depth_m": (("lat", "lon"), np.full((2, 2), 1500.0))},
        coords={"lat": lat, "lon": lon},
    )
    save_nc(bath, tmp_path / "bathy.nc")
    cfg = {
        "reviewed": True,
        "mode": "research_blended",
        "start": "2021-01-01",
        "end": "2021-01-03",
        "lat": [10, 10.25],
        "lon": [85, 85.25],
        "step": 0.25,
        "channels": {
            c: {
                "path": str(tmp_path / "input.nc"),
                "variable": c,
                "source_units": "native",
                "qc_variable": "qc",
                "accepted_qc": [1],
                "age_variable": "age",
                "spatial_tolerance_deg": 0.1,
            }
            for c in CHANNELS
        },
        "target": {
            "path": str(tmp_path / "target.nc"),
            "temperature": "thetao",
            "salinity": "so",
            "temperature_units": "degrees_C",
            "salinity_units": "1e-3",
            "convention": "potential",
            "surface_convention": "copy_shallowest_to_zero",
            "spatial_tolerance_deg": 0.1,
        },
        "bathymetry": {
            "path": str(tmp_path / "bathy.nc"),
            "variable": "depth_m",
            "spatial_tolerance_deg": 0.1,
        },
    }
    prepare(cfg, tmp_path / "cube.nc")
    ds = load_cube(tmp_path / "cube.nc")
    assert np.isnan(ds.inputs.values[0, :, 0, 0]).all()
    assert (
        ds.target.values[0, -1, 0, 0] > 20
    )  # in-situ pressure correction, not a relabelled potential temperature
    assert np.isfinite(ds.target.values).all()
    bad = copy.deepcopy(cfg)
    bad["reviewed"] = False
    with pytest.raises(ValueError, match="STOP 2"):
        prepare(bad, tmp_path / "bad.nc")
