"""Explicit source mappings. No silent variable inference or QC bypass."""

import glob
import json
from pathlib import Path
import numpy as np
import xarray as xr
import gsw
from .contracts import CHANNELS, DEPTHS, UNITS, validate_cube, save_nc, dump, sha256


def read_source(spec):
    paths = sorted(glob.glob(spec["path"]))
    if not paths:
        raise FileNotFoundError(spec["path"])
    datasets = []
    for path in paths:
        with xr.open_dataset(path) as f:
            datasets.append(f.load())
    ds = xr.combine_by_coords(datasets) if len(datasets) > 1 else datasets[0]
    ds = ds.rename(
        {
            k: v
            for k, v in spec.get("rename", {}).items()
            if k in ds.dims or k in ds.coords
        }
    )
    if "lon" in ds.coords:
        ds = ds.assign_coords(lon=((ds.lon + 180) % 360) - 180).sortby("lon")
    if "lat" in ds.coords:
        ds = ds.sortby("lat")
    return ds, paths


def inventory(folder, out):
    rows = []
    for p in sorted(Path(folder).rglob("*.nc")):
        with xr.open_dataset(p) as ds:
            rows.append(
                {
                    "path": str(p),
                    "bytes": p.stat().st_size,
                    "sha256": sha256(p),
                    "dims": dict(ds.sizes),
                    "variables": {
                        k: {"dims": list(v.dims), "units": v.attrs.get("units")}
                        for k, v in ds.data_vars.items()
                    },
                }
            )
    dump(out, rows)
    return rows


def spatial(da, lat, lon, tolerance):
    # Nearest source cell only within explicit angular tolerance. Do not smooth across missing cells.
    return da.reindex(lat=lat, lon=lon, method="nearest", tolerance=tolerance)


def prepare(config, out):
    cfg = config
    if not cfg.get("reviewed"):
        raise ValueError(
            "STOP 2: review source mappings, QC and units before setting reviewed: true"
        )
    if cfg["mode"] not in ["satellite_observation", "research_blended"]:
        raise ValueError("Explicit source mode required")
    lat = np.arange(cfg["lat"][0], cfg["lat"][1] + cfg["step"] / 2, cfg["step"])
    lon = np.arange(cfg["lon"][0], cfg["lon"][1] + cfg["step"] / 2, cfg["step"])
    dates = np.arange(
        np.datetime64(cfg["start"]), np.datetime64(cfg["end"]) + np.timedelta64(1, "D")
    )
    values = []
    ages = []
    manifest = []
    for channel, unit in zip(CHANNELS, UNITS):
        spec = cfg["channels"][channel]
        ds, paths = read_source(spec)
        da = ds[spec["variable"]]
        if da.attrs.get("units") != spec["source_units"]:
            raise ValueError(f'{channel}: unexpected units {da.attrs.get("units")}')
        if spec.get("qc_variable"):
            da = da.where(ds[spec["qc_variable"]].isin(spec["accepted_qc"]))
        elif (
            not spec.get("qc_review_note")
            or "REPLACE" in spec["qc_review_note"].upper()
        ):
            raise ValueError(f"{channel}: provide QC mapping or documented QC review")
        da = da * spec.get("scale", 1) + spec.get("offset", 0)
        if set(da.dims) != {"time", "lat", "lon"}:
            raise ValueError(
                f"{channel}: expected rectilinear time/lat/lon; got {da.dims}"
            )
        da = da.transpose("time", "lat", "lon")
        # Daily retrospective mean, retaining explicit missing days. No forward fill.
        daily = da.resample(time="1D").mean(skipna=True)
        daily = spatial(daily, lat, lon, spec["spatial_tolerance_deg"]).reindex(
            time=dates
        )
        if "age_variable" not in spec:
            raise ValueError(
                f"{channel}: age_variable required; prepare actual ages from observation-window metadata"
            )
        age = ds[spec["age_variable"]]
        if age.attrs.get("units") not in ["hours", "hour", "h"]:
            raise ValueError("age_variable must be in hours")
        if "lat" not in age.dims:
            age = age.broadcast_like(da)
        age = spatial(
            age.resample(time="1D").max(), lat, lon, spec["spatial_tolerance_deg"]
        ).reindex(time=dates)
        values.append(daily.values)
        ages.append(
            np.where(
                np.isfinite(daily.values),
                age.transpose("time", "lat", "lon").values,
                np.nan,
            )
        )
        manifest.append(
            {
                "channel": channel,
                "units": unit,
                "spec": spec,
                "files": [{"path": p, "sha256": sha256(p)} for p in paths],
            }
        )
    bspec = cfg["bathymetry"]
    bds, bpaths = read_source(bspec)
    bathy = (
        spatial(
            bds[bspec["variable"]] * bspec.get("scale", 1),
            lat,
            lon,
            bspec["spatial_tolerance_deg"],
        )
        .transpose("lat", "lon")
        .values
    )
    if bathy.shape != (len(lat), len(lon)) or not np.isfinite(bathy).all():
        raise ValueError("Bathymetry must cover every grid coordinate")
    spec = cfg["target"]
    tds, tpaths = read_source(spec)
    theta = tds[spec["temperature"]].transpose("time", "depth", "lat", "lon")
    sal = tds[spec["salinity"]].transpose("time", "depth", "lat", "lon")
    if (
        theta.attrs.get("units") != spec["temperature_units"]
        or sal.attrs.get("units") != spec["salinity_units"]
    ):
        raise ValueError("Target temperature/salinity unit mismatch")
    t = theta.values * spec.get("temperature_scale", 1) + spec.get(
        "temperature_offset", 0
    )
    z = theta.depth.values
    if np.any(np.diff(z) <= 0):
        raise ValueError("Target depth must increase")
    p = gsw.p_from_z(-z[:, None, None], tds.lat.values[None, :, None])
    sa = gsw.SA_from_SP(
        sal.values,
        p,
        tds.lon.values[None, None, None, :],
        tds.lat.values[None, None, :, None],
    )
    temp = (
        gsw.t_from_CT(sa, gsw.CT_from_pt(sa, t), p)
        if spec["convention"] == "potential"
        else t
    )
    if spec["convention"] not in ["potential", "in_situ"]:
        raise ValueError("Unknown temperature convention")
    target = xr.DataArray(temp, dims=theta.dims, coords=theta.coords)
    # The nominal 0 m level may sit a fraction of a metre above the source's
    # shallowest physical level (e.g. GLORYS ~0.494 m). Treat only that tiny
    # shallow-end gap as the surface; never turn a materially deeper source
    # level into a 0 m extrapolation. The deep end remains strict.
    NEAR_SURFACE_TOLERANCE_M = 1.0
    if (
        z[0] > 0
        and z[0] <= NEAR_SURFACE_TOLERANCE_M
        and spec.get("surface_convention") == "copy_shallowest_to_zero"
    ):
        surface = (
            target.isel(depth=0, drop=True)
            .expand_dims(depth=[0])
            .transpose(*theta.dims)
        )
        target = xr.concat([surface, target], dim="depth")
    target = target.interp(depth=DEPTHS)  # outside source support remains NaN
    target = (
        spatial(target, lat, lon, spec["spatial_tolerance_deg"])
        .reindex(time=dates)
        .transpose("time", "depth", "lat", "lon")
    )
    wet = (DEPTHS[:, None, None] <= bathy) & (bathy > 0)
    inputs = np.stack(values, axis=1).astype("float32")
    ages = np.stack(ages, axis=1).astype("float32")
    inputs[:, :, bathy <= 0] = np.nan
    ages[:, :, bathy <= 0] = np.nan
    ds = xr.Dataset(
        {
            "inputs": (("time", "channel", "lat", "lon"), inputs),
            "age_hours": (("time", "channel", "lat", "lon"), ages),
            "target": (
                ("time", "depth", "lat", "lon"),
                np.where(wet, target.values, np.nan).astype("float32"),
            ),
            "bathymetry": (("lat", "lon"), bathy.astype("float32")),
        },
        coords={
            "time": dates,
            "channel": CHANNELS,
            "depth": DEPTHS,
            "lat": lat,
            "lon": lon,
        },
        attrs={
            "source_mode": cfg["mode"],
            "temperature_convention": "in_situ_degC",
            "surface_convention": spec.get("surface_convention", "no_extrapolation"),
            "surface_tolerance_m": NEAR_SURFACE_TOLERANCE_M,
            "availability_mode": "retrospective; not an as-issued replay",
        },
    )
    validate_cube(ds)
    save_nc(ds, out)
    dump(
        Path(out).with_suffix(".sources.json"),
        {
            "channels": manifest,
            "target": spec,
            "bathymetry": bspec,
            "target_files": [{"path": p, "sha256": sha256(p)} for p in tpaths],
            "bathymetry_files": [{"path": p, "sha256": sha256(p)} for p in bpaths],
        },
    )
    return ds
