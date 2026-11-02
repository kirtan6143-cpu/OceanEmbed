"""Daily cube -> lazy temporal windows, training-only transforms and spatial patches."""

import warnings
import numpy as np
import xarray as xr
from .contracts import CHANNELS, DEPTHS, save_nc


def split_indices(ds, config):
    dates = ds.time.values.astype("datetime64[D]")
    result = {}
    used = set()
    window = config["window"]
    embargo = config.get("embargo_days", 0)
    previous_end = None
    for name in ["train", "validation", "calibration", "test"]:
        start, end = map(np.datetime64, config["splits"][name])
        if start < dates[0] or end > dates[-1]:
            raise ValueError(f"{name}: cube does not cover configured dates")
        if start > end or (previous_end is not None and start <= previous_end):
            raise ValueError("Splits must be chronological and disjoint")
        # All L input frames stay within the same partition. Extra source-window embargo configurable.
        ids = np.flatnonzero(
            (dates >= start + np.timedelta64(window - 1 + embargo, "D"))
            & (dates <= end)
        )
        if not len(ids):
            raise ValueError(f"No valid windows in {name}")
        if used.intersection(ids):
            raise ValueError("Overlapping splits")
        used.update(ids)
        result[name] = ids
        previous_end = end
    return result


def fit_transforms(ds, config, out):
    start, end = config["splits"]["train"]
    train = ds.sel(time=slice(start, end))
    x = np.where(
        train.age_hours.values <= config["max_age_hours"], train.inputs.values, np.nan
    )
    mean = np.nanmean(x, axis=(0, 2, 3))
    std = np.nanstd(x, axis=(0, 2, 3))
    if not np.isfinite(mean).all():
        raise ValueError("A channel has no valid training data")
    std = np.maximum(std, 1e-5)
    monthly = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for month in range(1, 13):
            group = train.target.where(train.time.dt.month == month, drop=True)
            if not group.sizes["time"]:
                raise ValueError(
                    f"Month {month} absent: need a full seasonal training year"
                )
            monthly.append(np.nanmean(group.values, axis=0))
    clim = np.stack(monthly).astype("float32")
    transform = xr.Dataset(
        {
            "climatology": (("month", "depth", "lat", "lon"), clim),
            "mean": ("channel", mean),
            "std": ("channel", std),
        },
        coords={
            "month": np.arange(1, 13),
            "depth": DEPTHS,
            "lat": ds.lat,
            "lon": ds.lon,
            "channel": CHANNELS,
        },
        attrs={
            "train_start": start,
            "train_end": end,
            "source_mode": ds.attrs["source_mode"],
        },
    )
    save_nc(transform, out)
    return transform


def prior_for(ds, transform, idx):
    # Interpolate between actual calendar month midpoints, including leap years.
    import pandas as pd

    date = pd.Timestamp(ds.time.values[idx])
    m = date.month
    mid = pd.Timestamp(year=date.year, month=m, day=15)
    if date >= mid:
        a = mid
        b = mid + pd.DateOffset(months=1)
        ma = m
        mb = m % 12 + 1
    else:
        a = mid - pd.DateOffset(months=1)
        b = mid
        ma = (m - 2) % 12 + 1
        mb = m
    weight = (date - a) / (b - a)
    return (
        (1 - weight) * transform.climatology.sel(month=ma).values
        + weight * transform.climatology.sel(month=mb).values
    ).astype("float32")


def static_fields(ds):
    yy, xx = np.meshgrid(ds.lat.values, ds.lon.values, indexing="ij")
    b = ds.bathymetry.values
    return np.stack(
        [yy / 90, xx / 180, np.log1p(np.maximum(b, 0)) / 10, (b > 0).astype(float)]
    ).astype("float32")


def inputs_for(ds, transform, idx, window, max_age):
    x = ds.inputs.values[idx - window + 1 : idx + 1]
    age = ds.age_hours.values[idx - window + 1 : idx + 1]
    valid = np.isfinite(x) & np.isfinite(age) & (age <= max_age)
    norm = (x - transform["mean"].values[None, :, None, None]) / transform[
        "std"
    ].values[None, :, None, None]
    return np.concatenate(
        [
            np.where(valid, norm, 0),
            valid.astype("float32"),
            np.where(valid, np.minimum(age / max_age, 1), 1),
        ],
        axis=1,
    ).astype("float32")


class Windows:
    """torch Dataset-compatible. Cube resident in RAM; check inventory before large runs.

    Crop placement is reproducible but not fixed: it is seeded from
    (base seed, epoch, sample index), so a validation/test split with
    vary_crops=False sees the same crop every epoch (comparable checkpoint
    selection), while a training split with vary_crops=True sees a
    different, still-deterministic crop each epoch (better spatial
    coverage than a fixed modulo pattern that can alias against the
    grid dimensions).
    """

    def __init__(self, ds, transform, indices, config, patch=None, vary_crops=False):
        self.ds = ds
        self.transform = transform
        self.indices = indices
        self.cfg = config
        self.static = static_fields(ds)
        self.patch = patch
        self.vary_crops = vary_crops
        self.seed = config.get("seed", 42)
        self.epoch = 0

    def set_epoch(self, epoch):
        """Call once per epoch on the train-split dataset before iterating it."""
        self.epoch = int(epoch)

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, i):
        idx = int(self.indices[i])
        prior = prior_for(self.ds, self.transform, idx)
        x = inputs_for(
            self.ds, self.transform, idx, self.cfg["window"], self.cfg["max_age_hours"]
        )
        target = self.ds.target.values[idx].copy()
        target[~np.isfinite(prior)] = np.nan
        # Require every channel to have at least one valid frame in the window.
        support = np.all(np.any(x[:, 7:14] > 0, axis=0), axis=0)
        target[:, ~support] = np.nan
        h, w = target.shape[-2:]
        p = self.patch
        if p:
            p = min(p, h, w)
            epoch_key = self.epoch if self.vary_crops else 0
            rng = np.random.default_rng((self.seed, epoch_key, idx))
            y = int(rng.integers(0, h - p + 1))
            xx = int(rng.integers(0, w - p + 1))
            sy = slice(y, y + p)
            sx = slice(xx, xx + p)
        else:
            sy = slice(None)
            sx = slice(None)
        return (
            x[:, :, sy, sx],
            np.nan_to_num(prior[:, sy, sx]),
            self.static[:, sy, sx],
            target[:, sy, sx],
        )
