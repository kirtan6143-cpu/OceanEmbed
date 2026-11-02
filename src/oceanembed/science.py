"""Conservative thermal diagnostics: missing brackets remain unavailable."""

import numpy as np


def diagnostics(depth, temp):
    z = np.asarray(depth, float)
    t = np.asarray(temp, float)
    out = {"d26_m": None, "tchp_kj_cm2": None, "mld_t_m": None, "reason": None}
    if len(z) != len(t) or np.any(np.diff(z) <= 0):
        raise ValueError("Invalid profile")
    if z[0] != 0 or not np.isfinite(t[0]):
        return {**out, "reason": "No valid surface support"}
    if t[0] < 26:
        out.update(d26_m=0.0, tchp_kj_cm2=0.0)
    else:
        crossing = None
        for i in range(1, len(z)):
            if not np.isfinite(t[i]):
                break
            if t[i] <= 26:
                crossing = (
                    z[i - 1] + (26 - t[i - 1]) * (z[i] - z[i - 1]) / (t[i] - t[i - 1])
                    if t[i] != t[i - 1]
                    else z[i - 1]
                )
                zz = np.r_[z[:i], crossing]
                tt = np.r_[t[:i], 26.0]
                integral = np.sum(np.diff(zz) * ((tt[:-1] - 26) + (tt[1:] - 26)) / 2)
                out.update(
                    d26_m=float(crossing),
                    tchp_kj_cm2=float(1025 * 3990 * integral / 1e7),
                )
                break
        if crossing is None:
            out["reason"] = "26 C crossing not bracketed; D26 and TCHP withheld"
    j = np.searchsorted(z, 10)
    if j < len(z) and z[j] == 10 and np.isfinite(t[j]):
        threshold = t[j] - 0.2
        for i in range(j + 1, len(z)):
            if not np.isfinite(t[i]):
                break
            if t[i] <= threshold:
                out["mld_t_m"] = float(
                    z[i - 1]
                    + (threshold - t[i - 1]) * (z[i] - z[i - 1]) / (t[i] - t[i - 1])
                )
                break
    return out


def field_diagnostics(depths, temperature):
    """Per-cell D26/TCHP/MLD-T over a full [depth, lat, lon] field.

    Loops diagnostics() over every cell rather than trying to vectorize the
    26 C crossing search, since the crossing depth differs cell to cell and
    a masked/vectorized version would either need padding tricks that are
    easy to get subtly wrong or would just re-implement the same per-cell
    loop with more code. For the grid sizes this project runs at (native
    resolution rasters, not fine-resolution imagery) this is fast enough to
    serve on request; results are cached at the API layer like the other
    field endpoints.

    Returns 2D arrays (NaN where diagnostics() returned None) so callers can
    feed them straight into the same map/reliability pipeline as temperature.
    """
    z = np.asarray(depths, float)
    t = np.asarray(temperature, float)
    if t.ndim != 3 or t.shape[0] != len(z):
        raise ValueError("temperature must be [depth, lat, lon] matching depths")
    ny, nx = t.shape[1:]
    d26 = np.full((ny, nx), np.nan)
    tchp = np.full((ny, nx), np.nan)
    mld = np.full((ny, nx), np.nan)
    for y in range(ny):
        for x in range(nx):
            out = diagnostics(z, t[:, y, x])
            if out["d26_m"] is not None:
                d26[y, x] = out["d26_m"]
            if out["tchp_kj_cm2"] is not None:
                tchp[y, x] = out["tchp_kj_cm2"]
            if out["mld_t_m"] is not None:
                mld[y, x] = out["mld_t_m"]
    return {"d26_m": d26, "tchp_kj_cm2": tchp, "mld_t_m": mld}


def heat_events(dates, temp, mean, threshold):
    """Retrospective contiguous >=5-day events; no bridging missing observations."""
    dates = np.asarray(dates, dtype="datetime64[D]")
    t = np.asarray(temp, float)
    mean = np.broadcast_to(mean, t.shape)
    threshold = np.broadcast_to(threshold, t.shape)
    if len(dates) != len(t) or np.any(np.diff(dates) != np.timedelta64(1, "D")):
        raise ValueError("Daily sequence required")
    valid = (
        np.isfinite(t) & np.isfinite(mean) & np.isfinite(threshold) & (threshold > mean)
    )
    exceed = valid & (t > threshold)
    events = []
    start = None
    for i, on in enumerate(np.r_[exceed, False]):
        if on and start is None:
            start = i
        if not on and start is not None:
            if i - start >= 5:
                ratio = (t[start:i] - mean[start:i]) / (
                    threshold[start:i] - mean[start:i]
                )
                category = ["Moderate", "Strong", "Severe", "Extreme"][
                    min(3, max(0, int(np.max(ratio)) - 1))
                ]
                events.append(
                    {
                        "start": str(dates[start]),
                        "end": str(dates[i - 1]),
                        "duration_days": i - start,
                        "peak_anomaly": float(np.max(t[start:i] - mean[start:i])),
                        "category": category,
                    }
                )
            start = None
    return events


def score(observed, predicted):
    a = np.asarray(observed, float)
    b = np.asarray(predicted, float)
    valid = np.isfinite(a) & np.isfinite(b)
    a = a[valid]
    b = b[valid]
    e = b - a
    return {
        "n": len(a),
        "rmse": float(np.sqrt(np.mean(e**2))) if len(a) else None,
        "mae": float(np.mean(abs(e))) if len(a) else None,
        "bias": float(np.mean(e)) if len(a) else None,
        "correlation": (
            float(np.corrcoef(a, b)[0, 1])
            if len(a) > 1 and np.std(a) > 0 and np.std(b) > 0
            else None
        ),
    }


def conformal(errors, alpha=0.1):
    """Unscaled simultaneous profile intervals; one complete profile per row."""
    errors = np.asarray(errors, float)
    if not 0 < alpha < 1 or errors.ndim != 2:
        raise ValueError("Expected profile x depth errors and 0 < alpha < 1")
    good = np.all(np.isfinite(errors), axis=1)
    s = np.max(abs(errors[good]), axis=1)
    n = len(s)
    rank = int(np.ceil((n + 1) * (1 - alpha)))
    if n == 0 or rank > n:
        raise ValueError("Too few complete calibration profiles for finite interval")
    return {
        "q_degC": float(np.sort(s)[rank - 1]),
        "n_profiles": n,
        "alpha": alpha,
        "kind": "simultaneous_absolute",
        "assumptions": "Exchangeable calibration/test profiles; inspect grouped empirical coverage",
    }
