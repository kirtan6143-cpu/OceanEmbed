"""Tiled inference with receptive-field halo; native scientific grid preserved."""

import json
import hashlib
from pathlib import Path
import numpy as np
import torch
import xarray as xr
from .contracts import DEPTHS, CHANNELS, save_nc, dump, sha256
from .dataset import inputs_for, prior_for, static_fields, split_indices
from .training import load_model
from .science import score
from .provenance import grid_fingerprint, json_fingerprint, file_or_none, inherited_attrs


@torch.inference_mode()
def predict_day(model, x, prior, static, tile=64, halo=3):
    # Two 3x3 spatial convolutions + one 3x3 decoder -> radius 3.
    if halo < 3:
        raise ValueError("This architecture requires a halo of at least three cells")
    # `tile` was never validated. A non-positive tile makes
    # `range(0, h, tile)` iterate zero times (range with a non-positive step
    # and start < stop is empty in Python), so the loop below never runs and
    # `result` -- allocated via np.empty_like, which does NOT zero-initialise
    # -- is returned as uninitialised memory. Reproduced directly: tile=-1
    # returned a full array of whatever garbage bytes happened to be there,
    # with no exception and no indication anything was wrong.
    if not isinstance(tile, int) or tile <= 0:
        raise ValueError(f"tile must be a positive integer, got {tile!r}")
    h, w = prior.shape[-2:]
    result = np.empty_like(prior)
    device = next(model.parameters()).device
    for y in range(0, h, tile):
        for xx in range(0, w, tile):
            y1 = min(h, y + tile)
            x1 = min(w, xx + tile)
            a = max(0, y - halo)
            b = min(h, y1 + halo)
            c = max(0, xx - halo)
            d = min(w, x1 + halo)
            tensors = [
                torch.as_tensor(v[None], dtype=torch.float32, device=device)
                for v in [
                    x[:, :, a:b, c:d],
                    np.nan_to_num(prior[:, a:b, c:d]),
                    static[:, a:b, c:d],
                ]
            ]
            pred = model(*tensors)[0].cpu().numpy()
            result[:, y:y1, xx:x1] = pred[:, y - a : y1 - a, xx - c : x1 - c]
    return result


def run(ds, bundle, output, partition="test", limit=0, cube_path=None):
    torch.set_num_threads(2)
    model, tr, cfg = load_model(bundle)
    if not np.array_equal(ds.lat, tr.lat) or not np.array_equal(ds.lon, tr.lon):
        raise ValueError("Bundle and cube grids differ")
    ids = split_indices(ds, cfg)[partition]
    if limit:
        ids = ids[:limit]
    static = static_fields(ds)
    preds = []
    priors = []
    support = []
    wet = (DEPTHS[:, None, None] <= ds.bathymetry.values) & (ds.bathymetry.values > 0)
    for idx in ids:
        x = inputs_for(ds, tr, idx, cfg["window"], cfg["max_age_hours"])
        prior = prior_for(ds, tr, idx)
        good = np.all(np.any(x[:, 7:14] > 0, axis=0), axis=0)
        mask = wet & good[None] & np.isfinite(prior)
        pred = predict_day(model, x, prior, static, tile=cfg.get("tile", 64))
        preds.append(np.where(mask, pred, np.nan))
        priors.append(prior)
        support.append(mask.astype("int8"))
    result = xr.Dataset(
        {
            "temperature": (("time", "depth", "lat", "lon"), np.stack(preds)),
            "prior": (("time", "depth", "lat", "lon"), np.stack(priors)),
            "reference": (("time", "depth", "lat", "lon"), ds.target.values[ids]),
            "support": (("time", "depth", "lat", "lon"), np.stack(support)),
            "age_hours": (("time", "channel", "lat", "lon"), ds.age_hours.values[ids]),
            "bathymetry": ds.bathymetry,
        },
        coords={
            "time": ds.time.values[ids],
            "depth": DEPTHS,
            "lat": ds.lat,
            "lon": ds.lon,
            "channel": CHANNELS,
        },
        attrs={
            "source_mode": ds.attrs["source_mode"],
            "title": "OceanEmbed retrospective reconstruction",
            "partition": partition,
            "weights_sha256": sha256(Path(bundle) / "weights.pt"),
            "model_fingerprint": hashlib.sha256("".join(sha256(Path(bundle)/n) for n in ["weights.pt", "transforms.nc", "config.json"]).encode()).hexdigest(),
            "uncertainty_status": "unavailable until observational calibration",
            "source_cube_sha256": sha256(cube_path) if cube_path else "not supplied",
            "split_manifest_sha256": file_or_none(Path(bundle) / "split_manifest.json") or "not supplied",
            "inference_config_fingerprint": json_fingerprint(cfg),
            "Conventions": "CF-1.10",
            # V2: carry the cube's surface/temperature conventions so the
            # release verifier can confirm how the 0 m level was produced.
            **inherited_attrs(ds.attrs),
        },
    )
    result.attrs["grid_fingerprint"] = grid_fingerprint(result)
    result["anomaly"] = result.temperature - result.prior
    for name in ["temperature", "prior", "reference", "anomaly"]:
        result[name].attrs["units"] = "degC"
    result.temperature.attrs["standard_name"] = "sea_water_temperature"
    result.depth.attrs.update(units="m", positive="down")
    result.lat.attrs["units"] = "degrees_north"
    result.lon.attrs["units"] = "degrees_east"
    result.age_hours.attrs["units"] = "hours"
    result.bathymetry.attrs["units"] = "m"
    save_nc(result, output)
    metrics = []
    for j, z in enumerate(DEPTHS):
        y = result.reference.values[:, j]
        p = result.temperature.values[:, j]
        c = result.prior.values[:, j]
        common_y = np.where(np.isfinite(p), y, np.nan)
        metrics.append(
            {
                "depth": z,
                "model": score(y, p),
                "climatology": score(common_y, c),
                "anomaly": score(y - c, p - c),
            }
        )
    metrics_path = Path(output).with_suffix(".metrics.json")
    dump(
        metrics_path,
        {
            "source": (
                "synthetic"
                if ds.attrs["source_mode"] == "synthetic"
                else "GLORYS teacher"
            ),
            "partition": partition,
            "run_sha256": sha256(output),
            "model_fingerprint": result.attrs["model_fingerprint"],
            "grid_fingerprint": result.attrs["grid_fingerprint"],
            "source_cube_sha256": result.attrs["source_cube_sha256"],
            "metrics": metrics,
            "note": "This is not independent observational validation.",
        },
    )
    return result
