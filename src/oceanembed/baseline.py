"""Pointwise ridge regression on surface channels plus static context.

Two explicit stages, on purpose:

  select()   Fit coefficients on train; choose regularization per depth
             using validation only. Safe to run repeatedly while still
             developing the pipeline (STOP 2 / early STOP 3). Never
             touches test data.

  evaluate() Load the frozen coefficients select() already chose and score
             them once on a partition that was not used to pick anything
             -- normally test. Run this only when baseline development is
             otherwise finished (see docs/STOPS.md), the same rule the
             project applies to model checkpoint selection.

Calling evaluate() is a deliberate, separate action from select() so a
STOP-2-era workflow doc cannot accidentally cause someone to look at test
scores before the baseline is actually frozen.
"""

from pathlib import Path
import json
import numpy as np
from .contracts import load_cube, dump, sha256, DEPTHS
from .dataset import fit_transforms, inputs_for, prior_for, static_fields, split_indices
from .science import score

DEFAULT_LAMBDAS = (0.1, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)
FEATURES = 1 + 7 + 4  # bias + 7 surface channels + 4 static fields


def _persistence_for(ds, i):
    """Naive persistence: the estimate for day i is the observed field from the
    immediately preceding day, same cell and depth.

    Returns None when day i-1 is not exactly one day earlier (or does not
    exist). That is deliberate: persistence is only meaningful when its
    previous value and initialization are clearly defined, so a gap in the
    time axis must produce "no persistence estimate" rather than a silently
    stale value carried across the gap.
    """
    if i <= 0:
        return None
    times = ds.time.values.astype("datetime64[D]")
    if times[i] - times[i - 1] != np.timedelta64(1, "D"):
        return None
    return ds.target.values[i - 1].reshape(15, -1)


def _extract(ds, tr, cfg, s, indices):
    """Materialize features/targets once per index so repeated lambda trials
    (or a later evaluate() call) don't re-run the window/prior lookups."""
    rows = []
    for i in indices:
        x = inputs_for(ds, tr, i, cfg["window"], cfg["max_age_hours"])[-1]
        a = np.concatenate([np.ones_like(s[:1]), x[:7], s], axis=0).reshape(FEATURES, -1).T
        valid = np.all(x[7:14] > 0, axis=0).ravel()
        prior = prior_for(ds, tr, i).reshape(15, -1)
        y = ds.target.values[i].reshape(15, -1)
        rows.append((a, valid, prior, y, _persistence_for(ds, i)))
    return rows


def _score_partition(coef, rows):
    """Score every baseline on exactly the same cells.

    Persistence is only defined where a contiguous previous day exists, so it
    is scored on its own matched subset and reports its own n. Comparing a
    persistence RMSE computed on fewer points against a model RMSE computed on
    all points would not be like-for-like, so the per-baseline counts are kept
    and published rather than assumed equal.
    """
    obs = [[] for _ in DEPTHS]
    pred = [[] for _ in DEPTHS]
    clim = [[] for _ in DEPTHS]
    pers_obs = [[] for _ in DEPTHS]
    pers = [[] for _ in DEPTHS]
    for a, valid, prior, y, previous in rows:
        estimate = coef @ a.T + prior
        for z in range(15):
            good = valid & np.isfinite(y[z]) & np.isfinite(prior[z])
            obs[z].extend(y[z, good])
            pred[z].extend(estimate[z, good])
            clim[z].extend(prior[z, good])
            if previous is not None:
                pgood = good & np.isfinite(previous[z])
                pers_obs[z].extend(y[z, pgood])
                pers[z].extend(previous[z, pgood])
    return [
        {
            "depth": z,
            "ridge": score(obs[j], pred[j]),
            "climatology": score(obs[j], clim[j]),
            "persistence": score(pers_obs[j], pers[j]),
        }
        for j, z in enumerate(DEPTHS)
    ]


def select(cfg, out, lambdas=DEFAULT_LAMBDAS):
    """Fit + choose regularization on train/validation only. Does not read,
    score against, or otherwise touch the test partition."""
    lambdas = tuple(lambdas)
    if not lambdas or not np.isfinite(lambdas).all() or min(lambdas) <= 0:
        raise ValueError("Provide finite positive ridge candidates")
    lambdas = tuple(sorted(set(lambdas)))
    ds = load_cube(cfg["cube"])
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    tr = fit_transforms(ds, cfg, out / "transforms.nc")
    ids = split_indices(ds, cfg)
    s = static_fields(ds)
    xx = np.zeros((15, FEATURES, FEATURES))
    xy = np.zeros((15, FEATURES))
    n = np.zeros(15, int)

    # Deterministic spatial subsampling bounds cost; temporal training partition unchanged.
    for i in ids["train"]:
        x = inputs_for(ds, tr, i, cfg["window"], cfg["max_age_hours"])[-1]
        a = np.concatenate([np.ones_like(s[:1]), x[:7], s], axis=0).reshape(FEATURES, -1).T
        valid = np.all(x[7:14] > 0, axis=0).ravel()
        prior = prior_for(ds, tr, i)
        y = (ds.target.values[i] - prior).reshape(15, -1)
        for z in range(15):
            ii = np.flatnonzero(valid & np.isfinite(y[z]))[::4]
            xz = a[ii]
            v = y[z, ii]
            xx[z] += xz.T @ xz
            xy[z] += xz.T @ v
            n[z] += len(v)

    val_rows = _extract(ds, tr, cfg, s, ids["validation"])
    coef = np.zeros((15, FEATURES))
    chosen_lambda = np.zeros(15)
    lambda_selection = []
    for z in range(15):
        best_rmse, best_lambda, best_coef = np.inf, lambdas[-1], None
        trace = []
        for lam in lambdas:
            c = np.linalg.solve(xx[z] + np.eye(FEATURES) * lam, xy[z])
            m = _score_one_depth(c, z, val_rows)
            trace.append({"lambda": lam, "validation_rmse": m["rmse"]})
            if m["rmse"] is not None and m["rmse"] < best_rmse:
                best_rmse, best_lambda, best_coef = m["rmse"], lam, c
        if best_coef is None:
            best_lambda = lambdas[-1]
            best_coef = np.linalg.solve(xx[z] + np.eye(FEATURES) * best_lambda, xy[z])
        coef[z] = best_coef
        chosen_lambda[z] = best_lambda
        lambda_selection.append(
            {"depth": DEPTHS[z], "chosen_lambda": float(best_lambda),
             "validation_rmse": best_rmse if np.isfinite(best_rmse) else None,
             "trace": trace}
        )
    np.savez(out / "ridge.npz", coefficients=coef, training_counts=n, chosen_lambda=chosen_lambda)
    dump(
        out / "selection.json",
        {
            "source_mode": ds.attrs["source_mode"],
            "stage": "select",
            "config": {k: v for k, v in cfg.items() if k not in ["cube", "output"]},
            "cube_sha256": sha256(cfg["cube"]),
            "ridge_sha256": sha256(out/"ridge.npz"),
            "transforms_sha256": sha256(out/"transforms.nc"),
            "selected_on": "validation",
            "lambda_selection": lambda_selection,
            "note": (
                "Regularization chosen on validation only. Test was not read "
                "by this call. Run baseline.evaluate() separately, once "
                "baseline development is finished, to score on test."
            ),
        },
    )
    return out


def _score_one_depth(coef_z, z, rows):
    obs, pred = [], []
    for a, valid, prior, y, _previous in rows:
        good = valid & np.isfinite(y[z]) & np.isfinite(prior[z])
        if not np.any(good):
            continue
        estimate = coef_z @ a[good].T + prior[z, good]
        obs.extend(y[z, good])
        pred.extend(estimate)
    return score(obs, pred)


def evaluate(cfg, ridge_dir, out, partition="test"):
    """Load the frozen coefficients from select() and score them once on
    `partition`. Refuses validation, since select() already used it --
    scoring there again would just restate the number that chose the
    hyperparameter, not test anything new."""
    if partition != "test":
        raise ValueError(
            "validation already chose ridge_lambda in select(); evaluate on "
            "test (or another split untouched by select) instead"
        )
    ridge_dir = Path(ridge_dir)
    frozen = json.loads((ridge_dir/"selection.json").read_text())
    expected_cfg = {k: v for k, v in cfg.items() if k not in ["cube", "output"]}
    if frozen.get("config") != expected_cfg or frozen.get("cube_sha256") != sha256(cfg["cube"]):
        raise ValueError("Frozen baseline config/data differs; select a new baseline explicitly")
    for filename, key in [("ridge.npz", "ridge_sha256"), ("transforms.nc", "transforms_sha256")]:
        if frozen.get(key) != sha256(ridge_dir/filename):
            raise ValueError("Frozen baseline file checksum mismatch")
    npz = np.load(ridge_dir / "ridge.npz")
    coef = npz["coefficients"]
    ds = load_cube(cfg["cube"])
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    import xarray as xr

    with xr.open_dataset(ridge_dir / "transforms.nc") as f:
        tr = f.load()
    ids = split_indices(ds, cfg)[partition]
    s = static_fields(ds)
    rows = _extract(ds, tr, cfg, s, ids)
    metrics = _score_partition(coef, rows)
    dump(
        out / "metrics.json",
        {
            "source_mode": ds.attrs["source_mode"],
            "stage": "evaluate",
            "partition": partition,
            "ridge_source": str(ridge_dir),
            "ridge_sha256": sha256(ridge_dir / "ridge.npz"),
            "metrics": metrics,
            "baselines": ["ridge", "climatology", "persistence"],
            "note": (
                f"Frozen baseline scored once on '{partition}'; coefficients "
                "were not refit here. Persistence uses the previous day's "
                "observed field and is only defined where a contiguous "
                "previous day exists, so its per-depth n may be lower than "
                "the others -- compare counts, not just RMSE. No held-out "
                "observational (Argo/RAMA) evaluation in this function."
            ),
        },
    )
    return out
