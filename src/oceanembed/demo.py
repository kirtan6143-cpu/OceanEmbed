"""Deterministic synthetic fixture for engineering tests, not scientific evidence."""

import numpy as np
import xarray as xr
from .contracts import DEPTHS, CHANNELS, save_nc


def create(path, days=430):
    rng = np.random.default_rng(42)
    lat = np.linspace(5, 25, 16)
    lon = np.linspace(78, 100, 24)
    yy, xx = np.meshgrid(lat, lon, indexing="ij")
    # Deliberately simple synthetic wet domain. Real runs require bathymetry.
    bathy = 1800 + 500 * np.sin(xx / 3) * np.cos(yy / 5)
    bathy[((xx < 81) & (yy > 9)) | ((xx < 87) & (yy > 22))] = 0
    time = np.datetime64("2023-01-01") + np.arange(days)
    phase = np.arange(days)[:, None, None] * 2 * np.pi / 365
    sst = 28 + 1.8 * np.sin(phase) + 0.7 * np.cos(xx[None] / 4) - 0.03 * yy[None]
    sss = 34 + 0.6 * np.cos(phase) + np.zeros_like(sst)
    sla = 0.15 * np.sin(phase + xx[None] / 3) * np.cos(yy[None] / 7)
    u = 0.2 * np.sin(phase + yy[None] / 4) + np.zeros_like(sst)
    v = 0.15 * np.cos(phase + xx[None] / 5) + np.zeros_like(sst)
    windu = 3 * np.sin(phase) + np.zeros_like(sst)
    windv = 4 * np.cos(phase) + np.zeros_like(sst)
    inputs = np.stack([sst, sla, u, v, windu, windv, sss], axis=1).astype("float32")
    prior = 5 + (sst[:, None] - 5) * np.exp(-DEPTHS[None, :, None, None] / 220)
    temp = prior + 1.5 * sla[:, None] * np.exp(-DEPTHS[None, :, None, None] / 400)
    temp += rng.normal(0, 0.035, temp.shape)
    temp = np.where(
        (DEPTHS[None, :, None, None] <= bathy) & (bathy > 0), temp, np.nan
    ).astype("float32")
    inputs = np.where(bathy[None, None] > 0, inputs, np.nan)
    inputs[rng.random(inputs.shape) < 0.015] = np.nan
    age = np.where(np.isfinite(inputs), 12.0, np.nan).astype("float32")
    ds = xr.Dataset(
        {
            "inputs": (("time", "channel", "lat", "lon"), inputs),
            "age_hours": (("time", "channel", "lat", "lon"), age),
            "target": (("time", "depth", "lat", "lon"), temp),
            "bathymetry": (("lat", "lon"), bathy.astype("float32")),
        },
        coords={
            "time": time,
            "channel": CHANNELS,
            "depth": DEPTHS,
            "lat": lat,
            "lon": lon,
        },
        attrs={
            "source_mode": "synthetic",
            "title": "Synthetic engineering fixture; no observations",
            "surface_convention": "synthetic exact zero depth",
            "temperature_convention": "in_situ_degC",
        },
    )
    save_nc(ds, path)
    return ds
