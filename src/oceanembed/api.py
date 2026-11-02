"""Read-only local analyst API. Run paths are configured, never supplied by clients."""

import csv
import io
import json
import os
from functools import lru_cache
from pathlib import Path
from threading import RLock
import tempfile
import numpy as np
import xarray as xr
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response
from .contracts import clean, DEPTHS, save_nc
from .validation_contract import validate_matchup_payload
from .science import diagnostics, field_diagnostics, heat_events
from .performance import ResponseCache, fingerprint, cached_sha256
from . import reliability as rel

app = FastAPI(title="OceanEmbed-NIO", version="0.9.1")
app.add_middleware(ResponseCache, run_path=lambda: os.environ.get("OCEAN_RUN", "demo/runs/demo.nc"))
app.add_middleware(GZipMiddleware, minimum_size=2048, compresslevel=3)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
)


@lru_cache(maxsize=1)
def _load_dataset(identity):
    with xr.open_dataset(identity[0]) as f:
        ds = f.load()
    if fingerprint(identity[0]) != identity:
        raise HTTPException(409, "Run changed while loading; finish writing and retry.")
    return ds


_dataset_lock = RLock()


def dataset():
    path = Path(os.environ.get("OCEAN_RUN", "demo/runs/demo.nc"))
    with _dataset_lock:
        try:
            return _load_dataset(fingerprint(path))
        except FileNotFoundError:
            raise HTTPException(503, "No run available. Complete STOP 1 or set OCEAN_RUN.")


# Keep the existing test/admin reset contract.
dataset.cache_clear = _load_dataset.cache_clear


def day(date):
    ds = dataset()
    try:
        t = np.datetime64(date, "D")
    except ValueError:
        raise HTTPException(422, "Use YYYY-MM-DD")
    ids = np.flatnonzero(ds.time.values.astype("datetime64[D]") == t)
    if not len(ids):
        raise HTTPException(404, "Date unavailable in this run")
    return ds.isel(time=int(ids[0]))


def point(ds, lat, lon):
    if (
        not np.isfinite([lat, lon]).all()
        or not float(ds.lat.min()) <= lat <= float(ds.lat.max())
        or not float(ds.lon.min()) <= lon <= float(ds.lon.max())
    ):
        raise HTTPException(422, "Point outside run domain")
    return int(np.argmin(abs(ds.lat.values - lat))), int(
        np.argmin(abs(ds.lon.values - lon))
    )


def variable(ds, name):
    if name not in ["temperature", "anomaly"]:
        raise HTTPException(422, "Unsupported variable")
    return ds[name]


# Profile-derived diagnostics have no depth dimension of their own: TCHP, D26
# and MLD-T each describe the whole warm-water column at a point, so they do
# not change when the depth slider changes -- only the constituent full
# profile does. Mapping name -> (field_diagnostics key, display units).
PROFILE_DERIVED = {
    "tchp": ("tchp_kj_cm2", "kJ/cm2"),
    "d26": ("d26_m", "m"),
    "mld_t": ("mld_t_m", "m"),
}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/runs")
def runs():
    ds = dataset()
    freshness = None
    if "age_hours" in ds:
        # Freshness as-of the run's own latest date, not wall-clock time: this
        # is a retrospective research run, not a live feed, so "how fresh"
        # means "how old were the inputs relative to the day being shown",
        # not "how long ago did I load this file".
        latest = ds.age_hours.values[-1]
        finite = latest[np.isfinite(latest)]
        if finite.size:
            freshness = {"oldest_input_hours": float(finite.max()), "as_of_date": str(ds.time.values[-1])[:10]}
    return clean(
        {
            "dates": [str(v)[:10] for v in ds.time.values],
            "depths": DEPTHS,
            "bounds": [
                float(ds.lon.min()),
                float(ds.lat.min()),
                float(ds.lon.max()),
                float(ds.lat.max()),
            ],
            "source_mode": ds.attrs.get("source_mode"),
            "manifest": dict(ds.attrs),
            "intervals_available": "lower" in ds and "upper" in ds,
            "retrospective": True,
            "freshness": freshness,
        }
    )


@app.get("/field")
def field(
    date: str, depth: float = 100, var: str = "temperature", region: str = "Full domain"
):
    ds = day(date)
    if var not in PROFILE_DERIVED and depth not in DEPTHS:
        raise HTTPException(422, "Unsupported depth")
    # Region bounds are resolved but NOT applied to `ds` yet -- see the note
    # below, after reliability is computed, for why. `region` is validated
    # here so an unknown region still 422s before any work happens.
    if region == "Bay of Bengal":
        lon_bounds = (78, 100)
    elif region == "Arabian Sea":
        lon_bounds = (45, 78)
    elif region == "Full domain":
        lon_bounds = None
    else:
        raise HTTPException(422, "Unknown region")
    if lon_bounds is not None and not ((ds.lon.values >= lon_bounds[0]) & (ds.lon.values <= lon_bounds[1])).any():
        raise HTTPException(404, "Region unavailable in this run")

    if var in PROFILE_DERIVED:
        key, units = PROFILE_DERIVED[var]
        diag = field_diagnostics(DEPTHS, ds.temperature.values)
        values = diag[key]
        depth_echo = None
        depth_independent = True
        # Reliability for a profile-derived diagnostic must reflect the
        # diagnostic's OWN availability, not only whether the surface had
        # support. Previously field_states() was called with the surface
        # temperature as its main array, so its built-in "is this value
        # finite" check looked at surface finiteness while a completely
        # different array (`values`, the actual diagnostic) was what got
        # displayed. Reproduced directly: a constant 28 degC column has
        # valid surface support but no 26 degC crossing anywhere in the
        # water column, so TCHP/D26 are correctly null -- but the old call
        # reported that cell Supported anyway, because the surface
        # temperature it was actually checking was fine. bathymetry/age/
        # support below remain surface-based deliberately: those describe
        # whether the underlying satellite inputs were adequate, which is a
        # real and separate question from whether the diagnostic itself
        # resolved -- but the finite-value check must be on `values`.
        support_values = ds.temperature.sel(depth=DEPTHS[0]).values
        reliability_depth = DEPTHS[0]
        support_field = ds.support.sel(depth=DEPTHS[0]).values if "support" in ds else None
        # See the note above `support_values` just assigned: the finite-value
        # check that gates Abstain/no_value must run on the diagnostic
        # itself, not the surface temperature used for the other checks.
        finite_check_values = values
    else:
        values = variable(ds, var).sel(depth=depth).values
        units = "degC"
        depth_echo = depth
        depth_independent = False
        # Reliability is computed from temperature support regardless of
        # which variable is displayed: an anomaly is exactly as trustworthy
        # as the temperature it was derived from.
        support_values = ds.temperature.sel(depth=depth).values
        reliability_depth = depth
        support_field = ds.support.sel(depth=depth).values if "support" in ds else None
        finite_check_values = support_values

    state, reason = rel.field_states(
        finite_check_values,
        bathymetry=ds.bathymetry.values if "bathymetry" in ds else None,
        depth=reliability_depth,
        age_hours=ds.age_hours.values if "age_hours" in ds else None,
        support=support_field,
    )
    # Region cropping happens HERE, after reliability, and is applied
    # identically to lat/lon/values/state/reason together -- not by
    # re-slicing `ds` before reliability was computed. Confirmed this
    # mattered: `_edge_mask` (in reliability.py) marks a cell Caution/
    # domain_edge based on the shape of whatever array it's given. Cropping
    # `ds` first meant a cell interior to the true model domain, but near
    # the edge of a display-only regional crop, got `_edge_mask`'d against
    # the CROPPED array's shape -- so the same coordinate could read
    # Supported in "Full domain" and Caution/domain_edge in "Bay of Bengal"
    # for no reason but which menu option was selected. Computing on the
    # full grid first means edge status reflects the actual model boundary,
    # and cropping afterwards is a pure display operation that cannot
    # change it.
    estimated_z = None
    estimated_note = None
    display_depth_status = "native_reconstruction"
    estimate_source_depth = None
    reliability_applies_to_display = True
    if not depth_independent and depth == 1000.0:
        estimate_source_depth = 700.0
        estimated_z = variable(ds, var).sel(depth=estimate_source_depth).values
        display_depth_status = "display_estimate"
        reliability_applies_to_display = False
        estimated_note = (
            "1000 m is outside the native reference-data support (about 902 m). "
            "The map display uses the requested variable carried flat from 700 m. "
            "This is a display estimate, not a measured or model-predicted 1000 m "
            "value, and the reliability gate does not apply to the displayed estimate."
        )
    lat_out, lon_out = ds.lat.values, ds.lon.values
    if lon_bounds is not None:
        lon_mask = (lon_out >= lon_bounds[0]) & (lon_out <= lon_bounds[1])
        lon_out = lon_out[lon_mask]
        values = values[:, lon_mask]
        state = state[:, lon_mask]
        reason = reason[:, lon_mask]
        if estimated_z is not None:
            estimated_z = estimated_z[:, lon_mask]
    return clean(
        {
            "lat": lat_out,
            "lon": lon_out,
            "z": values,
            "estimated_z": estimated_z,
            "estimated_note": estimated_note,
            "depth": depth_echo,
            "depth_status": display_depth_status,
            "estimate_source_depth": estimate_source_depth,
            "reliability_applies_to_display": reliability_applies_to_display,
            "depth_independent": depth_independent,
            "units": units,
            "date": date,
            "mode": dataset().attrs.get("source_mode"),
            "reliability": state,
            "reliability_codes": {str(k): v for k, v in rel.codes().items()},
            "reliability_summary": rel.summarize(state),
            "reliability_thresholds": rel.thresholds(),
            # Per-cell reason code (e.g. "stale_inputs", "domain_edge") plus the
            # declared reason -> human text mapping, so a map tooltip can say
            # *why* a cell is Caution/Abstain instead of only which state it's
            # in. Additive only: existing "reliability" state array/semantics
            # are unchanged.
            "reliability_reason": reason,
            "reliability_reasons": rel.REASONS,
        }
    )


@app.get("/profile")
def profile(date: str, lat: float, lon: float):
    ds = day(date)
    y, x = point(ds, lat, lon)
    temp = ds.temperature.values[:, y, x]
    age = ds.age_hours.values[:, y, x]
    # Same domain-edge rule field_states() applies via _edge_mask, evaluated
    # for this single resolved cell so profile_state() can apply the
    # identical rule (see reliability.py's at_domain_edge docstring for why
    # this exists: profile and field previously used different rule sets).
    ny, nx = ds.lat.size, ds.lon.size
    k = min(rel.DEFAULT_EDGE_CELLS, ny, nx)
    at_edge = (y < k) or (y >= ny - k) or (x < k) or (x >= nx - k)
    return clean(
        {
            "depths": DEPTHS,
            "temperature": temp,
            "prior": ds.prior.values[:, y, x],
            "lat": float(ds.lat[y]),
            "lon": float(ds.lon[x]),
            "bathymetry": float(ds.bathymetry[y, x]),
            "age_hours": age,
            "channels": ds.channel.values,
            "diagnostics": diagnostics(DEPTHS, temp),
            "status": (
                "unavailable"
                if not np.isfinite(temp).any()
                else ds.attrs.get(
                    "uncertainty_status", "Estimate; uncertainty not calibrated"
                )
            ),
            "lower": ds.lower.values[:, y, x] if "lower" in ds else None,
            "upper": ds.upper.values[:, y, x] if "upper" in ds else None,
            "reliability": rel.profile_state(
                temp,
                depths=DEPTHS,
                bathymetry=float(ds.bathymetry[y, x]) if "bathymetry" in ds else None,
                age_hours=age,
                support=(
                    ds.support.values[:, y, x] if "support" in ds else None
                ),
                calibrated=("lower" in ds and "upper" in ds),
                at_domain_edge=at_edge,
                # Pass the actual per-depth values at this point, not just
                # whether the variables exist in the dataset -- see the
                # note above profile_state()'s calibrated_depths logic for
                # why the boolean alone was insufficient.
                lower=ds.lower.values[:, y, x] if "lower" in ds else None,
                upper=ds.upper.values[:, y, x] if "upper" in ds else None,
            ),
        }
    )


@app.get("/section")
def section(
    date: str,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    var: str = "temperature",
    n: int = Query(80, ge=2, le=250),
):
    ds = day(date)
    point(ds, lat1, lon1)
    point(ds, lat2, lon2)
    lats = np.linspace(lat1, lat2, n)
    lons = np.linspace(lon1, lon2, n)
    pts = [point(ds, a, b) for a, b in zip(lats, lons)]
    values = variable(ds, var).values
    z = np.stack([values[:, y, x] for y, x in pts], axis=1)
    bathy = [float(ds.bathymetry[y, x]) for y, x in pts]
    a = np.deg2rad(lats)
    b = np.deg2rad(lons)
    h = (
        np.sin(np.diff(a) / 2) ** 2
        + np.cos(a[:-1]) * np.cos(a[1:]) * np.sin(np.diff(b) / 2) ** 2
    )
    distance = np.r_[0, np.cumsum(6371 * 2 * np.arcsin(np.sqrt(np.clip(h, 0, 1))))]
    return clean(
        {
            "distance": distance,
            "depths": DEPTHS,
            "z": z,
            "bathymetry": bathy,
            "lat": lats,
            "lon": lons,
            "sampling": "nearest wet/land grid cell; no interpolation across land",
        }
    )


@app.get("/events")
def events(lat: float, lon: float, depth: float = 50):
    ds = dataset()
    y, x = point(ds, lat, lon)
    if depth not in DEPTHS:
        raise HTTPException(422, "Unsupported depth")
    t = ds.temperature.sel(depth=depth).values[:, y, x]
    result = {
        "dates": [str(v)[:10] for v in ds.time.values],
        "temperature": t,
        "events": [],
        "mean": None,
        "threshold": None,
        "status": "Unavailable: no reviewed daily heat-event baseline supplied.",
    }
    if "event_mean" in ds and "event_threshold" in ds:
        mean = ds.event_mean.sel(depth=depth).values[:, y, x]
        threshold = ds.event_threshold.sel(depth=depth).values[:, y, x]
        result.update(
            mean=mean,
            threshold=threshold,
            events=heat_events(ds.time.values, t, mean, threshold),
            status=(
                "Synthetic event illustration"
                if ds.attrs["source_mode"] == "synthetic"
                else "Retrospective research events"
            ),
        )
    return clean(result)


@app.get("/validation")
def validation(source: str = "Reanalysis"):
    if source not in ["Reanalysis", "Argo", "RAMA"]:
        raise HTTPException(422, "Unknown validation source")
    run = Path(os.environ.get("OCEAN_RUN", "demo/runs/demo.nc"))
    # A synthetic engineering fixture has no real prediction to score against
    # anything -- its "model" temperature is a deterministic offset applied
    # identically at every depth, so any RMSE computed from it is fabricated
    # and, if displayed, would show the same misleading flat number at all
    # 15 depths regardless of which source (Reanalysis/Argo/RAMA) was asked
    # for. Refuse to serve metrics for ANY source when the underlying run is
    # synthetic, rather than only gating Argo/RAMA as before.
    if dataset().attrs.get("source_mode") == "synthetic":
        return {
            "source": source,
            "metrics": [],
            "matchups": [],
            "note": (
                "This run is a synthetic engineering fixture. It has no "
                "trained prediction, so no RMSE/MAE/bias number is computed "
                "or shown for it under any source, including Reanalysis."
            ),
        }
    env_var = {"Argo": "OCEAN_VALIDATION", "RAMA": "OCEAN_RAMA"}.get(source)
    path = (
        Path(os.environ[env_var])
        if env_var and os.environ.get(env_var)
        else run.with_suffix(".metrics.json")
    )
    if source in ("Argo", "RAMA") and not os.environ.get(env_var):
        return {
            "source": source,
            "metrics": [],
            "matchups": [],
            "note": "No measured results loaded for this source.",
        }
    if not path.exists():
        return {
            "source": source,
            "metrics": [],
            "matchups": [],
            "note": "Run evaluation to populate this view.",
        }
    obj = json.loads(path.read_text())
    if source in ("Argo", "RAMA"):
        # source_mode == "synthetic" already returned above for every source;
        # reaching here means the run is real, so only the matchup payload
        # itself needs validating.
        try:
            validate_matchup_payload(obj, source)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        if not isinstance(obj.get("run_sha256"), str) or len(obj["run_sha256"]) != 64:
            raise HTTPException(409, "Missing or invalid run checksum")
    if source == "Argo":
        if obj.get("source") != "Argo":
            raise HTTPException(409, "Configured evaluation is not an Argo evaluation")
        if obj.get("run_sha256") not in [
            cached_sha256(run),
            dataset().attrs.get("base_run_sha256"),
        ]:
            raise HTTPException(409, "Evaluation does not belong to the selected run")
    if source == "RAMA":
        if obj.get("source") != "RAMA":
            raise HTTPException(409, "Configured evaluation is not a RAMA evaluation")
        if obj.get("run_sha256") not in [
            cached_sha256(run),
            dataset().attrs.get("base_run_sha256"),
        ]:
            raise HTTPException(409, "Evaluation does not belong to the selected run")
    return obj


@app.get("/baselines")
def baselines():
    """Frozen baseline comparison (ridge / climatology / persistence) produced
    by `baseline-evaluate`, pointed at by OCEAN_BASELINES.

    Served separately from /validation on purpose: these are reanalysis-target
    scores over the gridded cube, NOT held-out observational agreement. Merging
    them into the observation scorecard would blur exactly the distinction the
    evaluation design is built to preserve.
    """
    path = os.environ.get("OCEAN_BASELINES")
    if not path:
        return {
            "available": False,
            "note": (
                "No baseline comparison loaded. Run baseline-select then "
                "baseline-evaluate and set OCEAN_BASELINES."
            ),
        }
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, "OCEAN_BASELINES points to a missing file")
    obj = json.loads(p.read_text())
    if obj.get("stage") != "evaluate":
        raise HTTPException(
            409,
            "OCEAN_BASELINES must point at baseline-evaluate output, not a "
            "selection file (selection scores are validation-only).",
        )
    if obj.get("source_mode") == "synthetic":
        return {
            "available": False,
            "note": (
                "OCEAN_BASELINES points at a baseline computed on a synthetic "
                "cube. That comparison is not shown -- the same rule that "
                "blocks synthetic numbers on /validation applies here."
            ),
        }
    # Reproduced directly (this session): the check above only excludes
    # artifacts LABELLED synthetic -- it never checks whether the artifact's
    # mode actually matches the ACTIVE run's mode. A synthetic active run
    # accepted an unrelated artifact marked "research_blended" (a real-data
    # mode), since that string simply isn't "synthetic" and passed straight
    # through. Reject only a genuine, declared mismatch -- an artifact that
    # doesn't declare source_mode at all (an older or minimal fixture) is
    # left to the pre-existing rules rather than newly rejected, so this
    # doesn't regress artifacts that never carried the field; caught this
    # exact case via the project's own existing test suite, which fixtures
    # an evaluate-stage artifact with no source_mode key and (correctly)
    # expects it served. This does not yet bind baselines to cube/grid/
    # split identity (that needs a schema addition to what
    # baseline-evaluate writes, not done here), but it closes the
    # immediate cross-mode acceptance gap using data already available on
    # both sides.
    active_mode = dataset().attrs.get("source_mode")
    artifact_mode = obj.get("source_mode")
    if artifact_mode is not None and active_mode is not None and artifact_mode != active_mode:
        raise HTTPException(
            409,
            f"OCEAN_BASELINES source_mode ({artifact_mode!r}) does not "
            f"match the active run's mode ({active_mode!r})",
        )
    return clean(
        {
            "available": True,
            "reference": "reanalysis_target",
            "note": (
                "Gridded agreement with the training reference, not held-out "
                "observational skill. Compare per-depth n as well as RMSE: "
                "persistence is only defined where a contiguous previous day "
                "exists, so its sample count can differ."
            ),
            **obj,
        }
    )


def _cyclone_payload(kind):
    """Cyclone artifacts are produced offline by the cyclone CLI and pointed at
    by environment variables, exactly like Argo/RAMA evaluations. Nothing here
    computes a track on demand, and a payload that does not belong to the
    selected run is refused rather than drawn over the wrong ocean."""
    env_var = {"context": "OCEAN_CYCLONE", "wake": "OCEAN_COLD_WAKE"}[kind]
    path = os.environ.get(env_var)
    if not path:
        return {
            "available": False,
            "note": (
                "No cyclone context loaded. Build one with the cyclone CLI "
                f"and set {env_var}."
            ),
        }
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, f"{env_var} points to a missing file")
    obj = json.loads(p.read_text())
    expected = {"context": "cyclone_thermal_context", "wake": "cold_wake"}[kind]
    if obj.get("source") != expected:
        raise HTTPException(409, f"{env_var} is not a {expected} payload")
    run = Path(os.environ.get("OCEAN_RUN", "demo/runs/demo.nc"))
    # Reproduced directly (this session): `obj.get("run_sha256") not in
    # [cached_sha256(run), dataset().attrs.get("base_run_sha256")]` accepts
    # an artifact with NO checksum whenever the active run also has no
    # `base_run_sha256` attribute set, because `None in [hash, None]` is
    # True -- a checksum-less artifact and a checksum-less run "match" each
    # other. The Argo/RAMA path already guards against this (it rejects any
    # non-64-char-string run_sha256 before the membership check even runs);
    # this endpoint never had that guard. Fixed the same way: require a
    # valid-format checksum on the artifact, and build the allowed set from
    # only genuinely valid (non-null, correct-length) hashes -- so a run
    # with no base_run_sha256 contributes nothing to the allowed set rather
    # than contributing None.
    artifact_hash = obj.get("run_sha256")
    if not isinstance(artifact_hash, str) or len(artifact_hash) != 64:
        raise HTTPException(409, "Missing or invalid run checksum")
    allowed = {
        h for h in [cached_sha256(run), dataset().attrs.get("base_run_sha256")]
        if isinstance(h, str) and len(h) == 64
    }
    if artifact_hash not in allowed:
        raise HTTPException(409, "Cyclone context does not belong to the selected run")
    return {"available": True, **obj}


@app.get("/cyclone/context")
def cyclone_context():
    """Best-track points with reconstructed D26/TCHP at each in-domain point."""
    return clean(_cyclone_payload("context"))


@app.get("/cyclone/cold-wake")
def cyclone_cold_wake():
    """Matched pre/post-passage temperature change along the track."""
    return clean(_cyclone_payload("wake"))


@app.get("/export")
def export(
    date: str,
    format: str = "netcdf",
    depth: float = 100,
    var: str = "temperature",
    lat: float = 14,
    lon: float = 88,
):
    ds = day(date)
    variable(ds, var)
    if depth not in DEPTHS:
        raise HTTPException(422, "Unsupported depth")
    if format == "csv":
        obj = profile(date, lat, lon)
        s = io.StringIO()
        w = csv.writer(s)
        w.writerow(
            [
                "source_mode",
                "date",
                "lat",
                "lon",
                "depth_m",
                "temperature_degC",
                "prior_degC",
            ]
        )
        for z, t, c in zip(DEPTHS, obj["temperature"], obj["prior"]):
            w.writerow(
                [dataset().attrs["source_mode"], date, obj["lat"], obj["lon"], z, t, c]
            )
        payload = s.getvalue().encode()
        mime = "text/csv"
        ext = "csv"
    elif format == "netcdf":
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "selection.nc"
            save_nc(ds, p)
            payload = p.read_bytes()
        mime = "application/x-netcdf"
        ext = "nc"
    elif format == "png":
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib.figure import Figure

        fig = Figure(figsize=(9, 5))
        ax = fig.subplots()
        low, high = (-3, 3) if var == "anomaly" else (0, 32)
        im = ax.pcolormesh(
            ds.lon,
            ds.lat,
            variable(ds, var).sel(depth=depth),
            vmin=low,
            vmax=high,
            cmap="RdBu_r" if var == "anomaly" else "viridis",
            shading="nearest",
        )
        ax.set(
            xlabel="Longitude (degrees east)",
            ylabel="Latitude (degrees north)",
            title=f'{var} | {depth:g} m | {date} | {dataset().attrs["source_mode"]}',
        )
        fig.colorbar(
            im,
            ax=ax,
            label=(
                "Temperature anomaly (degC)"
                if var == "anomaly"
                else "Temperature (degC)"
            ),
        )
        bio = io.BytesIO()
        fig.savefig(bio, format="png", dpi=150, bbox_inches="tight")
        payload = bio.getvalue()
        mime = "image/png"
        ext = "png"
    else:
        raise HTTPException(422, "Choose netcdf, csv or png")
    return Response(
        payload,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="oceanembed-{date}.{ext}"'
        },
    )
