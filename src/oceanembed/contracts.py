"""Shared scientific contract and strict JSON serialization."""

import hashlib
import json
from pathlib import Path
import numpy as np
import xarray as xr

DEPTHS = np.array(
    [0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 700, 1000], dtype=float
)
CHANNELS = ["sst", "sla", "current_u", "current_v", "wind_u", "wind_v", "sss"]
UNITS = ["degC", "m", "m s-1", "m s-1", "m s-1", "m s-1", "1e-3"]


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(clean(value), indent=2, allow_nan=False), encoding="utf8"
    )


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_cube(ds):
    expected = {
        "inputs": ("time", "channel", "lat", "lon"),
        "age_hours": ("time", "channel", "lat", "lon"),
        "target": ("time", "depth", "lat", "lon"),
        "bathymetry": ("lat", "lon"),
    }
    for name, dims in expected.items():
        if name not in ds or ds[name].dims != dims:
            raise ValueError(f"{name} must have dimensions {dims}")
    if list(ds.channel.values) != CHANNELS:
        raise ValueError("Incorrect channel order")
    if not np.array_equal(ds.depth.values, DEPTHS):
        raise ValueError("Incorrect depth grid")
    for coord in ["lat", "lon", "depth"]:
        if not np.all(np.diff(ds[coord].values) > 0):
            raise ValueError(f"{coord} must increase")
    if len(ds.time) < 2 or not np.all(
        np.diff(ds.time.values) == np.timedelta64(1, "D")
    ):
        raise ValueError("Cube must contain unique consecutive daily timestamps")
    if np.any(ds.age_hours.values[np.isfinite(ds.age_hours.values)] < 0):
        raise ValueError("Negative observation age")
    if np.any(np.isfinite(ds.inputs.values) & ~np.isfinite(ds.age_hours.values)):
        raise ValueError("Every available input needs an age")
    wet = (ds.bathymetry.values[None] > 0) & (
        DEPTHS[:, None, None] <= ds.bathymetry.values[None]
    )
    if np.any(np.isfinite(ds.target.values) & ~wet[None]):
        raise ValueError("Targets exist below seafloor or on land")
    if not ds.attrs.get("source_mode"):
        raise ValueError("Missing source_mode")
    return ds


def save_nc(ds, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path, engine="h5netcdf")


def load_cube(path):
    with xr.open_dataset(path) as f:
        return validate_cube(f.load())
