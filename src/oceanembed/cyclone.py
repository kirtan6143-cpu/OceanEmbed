"""Retrospective cyclone thermal context: track overlay, upper-ocean heat
along the track, and a pre/post-passage cold-wake diagnostic.

Scope, stated once and enforced throughout: this module describes the ocean
thermal state around a storm that already happened. It does NOT forecast
intensity, it does NOT produce a rapid-intensification class, and the
difference between pre- and post-passage temperature alone does not prove
the storm caused it. Those limits are returned in every payload rather than
left to the UI to remember.

Track data is supplied through a reviewed config, the same discipline
prepare.py and rama.py apply to their sources. Official best-track archives
(IMD/RSMC for the North Indian Ocean) differ in column naming, wind
averaging period and category vocabulary, so this module will not guess a
layout: a real file must be inspected and the mapping reviewed before
reviewed: true is set. The source's own category labels are preserved
verbatim and never remapped onto a different scale (an IMD category is not
a Saffir-Simpson category).
"""

import csv
from pathlib import Path

import numpy as np
import xarray as xr

from .contracts import DEPTHS, dump, sha256
from .science import diagnostics

# Bump when the track schema's meaning changes.
TRACK_SCHEMA_VERSION = 1

REQUIRED_COLUMNS = ("name", "datetime", "lat", "lon")


def load_track(spec, out=None):
    """Read an official best-track CSV into a normalized, validated track.

    spec requires:
      reviewed: bool -- must be true.
      path: the best-track CSV.
      columns: mapping of this file's column names onto
               name / datetime / lat / lon, plus optional
               max_wind / pressure / category.
      wind_averaging: the source's wind averaging period as written
               (e.g. "3-minute sustained" for IMD). Required when
               max_wind is mapped, because a wind speed without its
               averaging period is not comparable across agencies.
      category_scheme: the source's category vocabulary (e.g. "IMD").
               Required when category is mapped.
      source: free-text provenance (agency, archive, retrieval date).
    """
    if not spec.get("reviewed"):
        raise ValueError(
            "STOP 2: inspect the real best-track file and review the column "
            "mapping, wind averaging period and category scheme before "
            "setting reviewed: true -- this module will not guess a layout"
        )
    columns = spec.get("columns") or {}
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise ValueError(f"Track column mapping missing: {', '.join(missing)}")
    if "max_wind" in columns and not spec.get("wind_averaging"):
        raise ValueError(
            "wind_averaging is required when max_wind is mapped: a wind speed "
            "without its averaging period cannot be compared across agencies"
        )
    if "category" in columns and not spec.get("category_scheme"):
        raise ValueError(
            "category_scheme is required when category is mapped: category "
            "labels are agency-specific and must not be silently remapped"
        )

    rows = []
    with open(spec["path"], newline="") as f:
        for raw in csv.DictReader(f):
            try:
                lat = float(raw[columns["lat"]])
                lon = float(raw[columns["lon"]])
            except (KeyError, TypeError, ValueError):
                continue
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 360):
                raise ValueError(f"Track point outside valid coordinates: {lat}, {lon}")
            stamp = str(raw[columns["datetime"]]).strip()
            try:
                when = np.datetime64(stamp)
            except ValueError:
                raise ValueError(f"Unparseable track datetime: {stamp!r}")
            point = {
                "name": str(raw[columns["name"]]).strip(),
                "datetime": str(when),
                "date": str(when.astype("datetime64[D]")),
                "lat": lat,
                # Normalize to -180..180 to match the run grid convention.
                "lon": (lon + 180) % 360 - 180,
            }
            for optional in ("max_wind", "pressure", "category"):
                col = columns.get(optional)
                if col and raw.get(col) not in (None, ""):
                    value = raw[col]
                    if optional == "category":
                        point[optional] = str(value).strip()
                    else:
                        try:
                            point[optional] = float(value)
                        except ValueError:
                            point[optional] = None
            rows.append(point)

    if not rows:
        raise ValueError("No usable track points found")
    rows.sort(key=lambda r: r["datetime"])
    if len({r["name"] for r in rows}) != 1:
        raise ValueError("Track file contains multiple storms; split them first")

    track = {
        "schema_version": TRACK_SCHEMA_VERSION,
        "name": rows[0]["name"],
        "points": rows,
        "start": rows[0]["datetime"],
        "end": rows[-1]["datetime"],
        "wind_averaging": spec.get("wind_averaging"),
        "category_scheme": spec.get("category_scheme"),
        "source": spec.get("source"),
        "source_sha256": sha256(spec["path"]),
        "note": (
            "Official best track, reproduced as issued. Wind averaging period "
            "and category vocabulary are the source agency's own and are not "
            "converted to any other scale."
        ),
    }
    if out:
        dump(out, track)
    return track


def _nearest(ds, lat, lon):
    if not (
        float(ds.lat.min()) <= lat <= float(ds.lat.max())
        and float(ds.lon.min()) <= lon <= float(ds.lon.max())
    ):
        return None
    return int(np.argmin(abs(ds.lat.values - lat))), int(
        np.argmin(abs(ds.lon.values - lon))
    )


def thermal_context(run_path, track, out=None):
    """Upper-ocean thermal state at each in-domain track point.

    For every track point that falls inside the run's domain and date range,
    report D26 and TCHP from the reconstructed profile at that location. Points
    outside the domain or outside the run's dates are returned with a reason
    rather than dropped silently, so a sparse overlay is visibly sparse instead
    of looking like a complete track.
    """
    with xr.open_dataset(run_path) as f:
        ds = f.load()
    times = ds.time.values.astype("datetime64[D]")
    out_points = []
    for p in track["points"]:
        record = {**p, "d26_m": None, "tchp_kj_cm2": None, "reason": None}
        day = np.datetime64(p["date"])
        hit = np.flatnonzero(times == day)
        if not len(hit):
            record["reason"] = "Date not in run"
            out_points.append(record)
            continue
        cell = _nearest(ds, p["lat"], p["lon"])
        if cell is None:
            record["reason"] = "Outside run domain"
            out_points.append(record)
            continue
        y, x = cell
        temp = ds.temperature.values[int(hit[0]), :, y, x]
        diag = diagnostics(DEPTHS, temp)
        record.update(
            d26_m=diag["d26_m"],
            tchp_kj_cm2=diag["tchp_kj_cm2"],
            reason=diag["reason"],
            grid_lat=float(ds.lat[y]),
            grid_lon=float(ds.lon[x]),
        )
        out_points.append(record)

    covered = [p for p in out_points if p["d26_m"] is not None]
    result = {
        "source": "cyclone_thermal_context",
        "name": track["name"],
        "schema_version": TRACK_SCHEMA_VERSION,
        "points": out_points,
        "points_total": len(out_points),
        "points_with_thermal_context": len(covered),
        "run_sha256": sha256(run_path),
        "source_mode": ds.attrs.get("source_mode"),
        "wind_averaging": track.get("wind_averaging"),
        "category_scheme": track.get("category_scheme"),
        "limits": (
            "Ocean thermal context for a past storm. Not an intensity or "
            "rapid-intensification forecast. High heat potential does not "
            "imply intensification; many atmospheric factors govern that."
        ),
    }
    if out:
        dump(out, result)
    return result


def cold_wake(run_path, track, depth=50.0, days=3, out=None):
    """Pre/post-passage temperature change at the track's own locations.

    At each track point, average `days` days strictly before passage and
    `days` days strictly after, at the same grid cell and depth, and report
    the difference. Both windows must be complete: a partial window yields
    no value and a stated reason, because averaging over a different number
    of days on each side would manufacture a difference that is an artefact
    of the window, not the ocean.
    """
    if depth not in DEPTHS:
        raise ValueError(f"depth must be one of the {len(DEPTHS)} contract depths")
    if days < 1:
        raise ValueError("days must be >= 1")
    with xr.open_dataset(run_path) as f:
        ds = f.load()
    times = ds.time.values.astype("datetime64[D]")
    zi = list(DEPTHS).index(depth)

    seen = set()
    records = []
    for p in track["points"]:
        cell = _nearest(ds, p["lat"], p["lon"])
        if cell is None:
            continue
        y, x = cell
        passage = np.datetime64(p["date"])
        key = (y, x, str(passage))
        if key in seen:
            continue
        seen.add(key)

        before_days = [passage - np.timedelta64(k, "D") for k in range(1, days + 1)]
        after_days = [passage + np.timedelta64(k, "D") for k in range(1, days + 1)]
        record = {
            "name": p["name"],
            "passage_date": str(passage),
            "lat": p["lat"],
            "lon": p["lon"],
            "grid_lat": float(ds.lat[y]),
            "grid_lon": float(ds.lon[x]),
            "depth": float(depth),
            "before_mean": None,
            "after_mean": None,
            "change_degC": None,
            "reason": None,
        }

        def window_mean(wanted):
            values = []
            for w in wanted:
                hit = np.flatnonzero(times == w)
                if not len(hit):
                    return None
                v = float(ds.temperature.values[int(hit[0]), zi, y, x])
                if not np.isfinite(v):
                    return None
                values.append(v)
            return float(np.mean(values))

        before = window_mean(before_days)
        after = window_mean(after_days)
        if before is None or after is None:
            record["reason"] = (
                f"Incomplete {days}-day window on one or both sides of passage"
            )
        else:
            record.update(
                before_mean=before, after_mean=after, change_degC=after - before
            )
        records.append(record)

    usable = [r for r in records if r["change_degC"] is not None]
    result = {
        "source": "cold_wake",
        "name": track["name"],
        "depth": float(depth),
        "window_days": int(days),
        "records": records,
        "locations_total": len(records),
        "locations_with_complete_windows": len(usable),
        "mean_change_degC": (
            float(np.mean([r["change_degC"] for r in usable])) if usable else None
        ),
        "run_sha256": sha256(run_path),
        "source_mode": ds.attrs.get("source_mode"),
        "limits": (
            "Difference between matched pre- and post-passage windows at the "
            "same cells. A negative change is consistent with a cold wake but "
            "does not by itself establish that the storm caused it; seasonal "
            "change, advection and reconstruction error also contribute."
        ),
    }
    if out:
        dump(out, result)
    return result
