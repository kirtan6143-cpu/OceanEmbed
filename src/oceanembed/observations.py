"""Argo profile conversion and bounded nearest-cell/time matchups."""

import csv
import glob
import hashlib
import json
from pathlib import Path
import numpy as np
import xarray as xr
import gsw
from .contracts import DEPTHS, dump, sha256
from .science import score, conformal
from .validation_contract import OBSERVATION_SCHEMA_VERSION, scheme_fingerprint, validate_matchup_payload

# Bump this whenever float_partition()'s bucketing rule changes shape (share
# defaults, bucket count, hash scheme). calibrate() and attach_intervals()
# refuse matchup files stamped with a different version, so a cached file
# produced under an old rule can never be silently mixed with a new one --
# it has to be regenerated with match() first.
PARTITION_SCHEME_VERSION = 2


def text(v):
    a = np.asarray(v).ravel()
    return "".join(x.decode() if isinstance(x, bytes) else str(x) for x in a).strip()


def argo_to_csv(pattern, out):
    rows = []
    for path in sorted(glob.glob(pattern, recursive=True)):
        with xr.open_dataset(path) as ds:
            for i in range(ds.sizes.get("N_PROF", 1)):
                d = ds.isel(N_PROF=i) if "N_PROF" in ds.dims else ds
                mode = text(d.DATA_MODE.values)
                suffix = "_ADJUSTED" if mode in ["A", "D"] else ""
                if "POSITION_QC" in d and text(d.POSITION_QC.values) not in ["1", "2"]:
                    continue
                if "JULD_QC" in d and text(d.JULD_QC.values) not in ["1", "2"]:
                    continue
                pn = "PRES" + suffix
                tn = "TEMP" + suffix
                if any(k not in d for k in [pn, tn, pn + "_QC", tn + "_QC"]):
                    continue
                p = d[pn].values
                t = d[tn].values

                def flags(name):
                    return np.asarray([text(v) for v in d[name].values])

                valid = (
                    np.isfinite(p)
                    & np.isfinite(t)
                    & np.isin(flags(pn + "_QC"), ["1", "2"])
                    & np.isin(flags(tn + "_QC"), ["1", "2"])
                )
                if valid.sum() < 2:
                    continue
                lat = float(d.LATITUDE)
                lon = float(d.LONGITUDE)
                z = -gsw.z_from_p(p[valid], lat)
                v = t[valid]
                order = np.argsort(z)
                z = z[order]
                v = v[order]
                z, unique = np.unique(z, return_index=True)
                v = v[unique]
                # Require each interpolation bracket to be at most 150 m; retain missing depth support.
                vals = np.interp(DEPTHS, z, v, left=np.nan, right=np.nan)
                for j, depth in enumerate(DEPTHS):
                    k = np.searchsorted(z, depth)
                    if 0 < k < len(z) and z[k] != depth and z[k] - z[k - 1] > 150:
                        vals[j] = np.nan
                float_id = text(d.PLATFORM_NUMBER.values)
                date = str(d.JULD.values)[:10]
                if date == "NaT" or not np.isfinite([lat, lon]).all():
                    continue
                profile_id = f"{float_id}-{text(d.CYCLE_NUMBER.values)}-{i}"
                for z0, t0 in zip(DEPTHS, vals):
                    if np.isfinite(t0):
                        rows.append(
                            {
                                "float_id": float_id,
                                "profile_id": profile_id,
                                "date": date,
                                "lat": lat,
                                "lon": lon,
                                "depth": z0,
                                "temperature": float(t0),
                                "data_mode": mode,
                            }
                        )
    if not rows:
        raise ValueError("No QC-approved profiles found")
    rows = list(
        {
            (r["float_id"], r["date"], r["profile_id"].rsplit("-", 1)[0], r["depth"]): r
            for r in rows
        }.values()
    )
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def float_partition(float_id, adaptation_share=0.2, calibration_share=0.2, buckets=1000):
    """Deterministic three-way float assignment: adaptation / calibration / test.

    The same float_id always lands in the same group, independent of call
    order, CSV row order, or how many times this runs. Adaptation floats are
    reserved here even though this release has no adaptation training stage
    yet (see BATCHES.md STOP 2/3): reserving them now means a future
    adaptation stage cannot accidentally reuse floats already spent on
    calibration or the final test, which would be leakage discovered too
    late to fix cheaply. Shares are configurable; defaults leave 60% of
    floats for test.
    """
    scheme_fingerprint(PARTITION_SCHEME_VERSION, adaptation_share, calibration_share, buckets)
    if adaptation_share < 0 or calibration_share < 0:
        raise ValueError("Shares must be non-negative")
    if adaptation_share + calibration_share >= 1:
        raise ValueError("adaptation_share + calibration_share must leave floats for test")
    b = int(hashlib.sha256(float_id.encode()).hexdigest()[:8], 16) % buckets
    a_cut = int(buckets * adaptation_share)
    c_cut = a_cut + int(buckets * calibration_share)
    if b < a_cut:
        return "adaptation"
    if b < c_cut:
        return "calibration"
    return "test"


def partition_summary(csv_path, adaptation_share=0.2, calibration_share=0.2):
    """Count distinct floats per reserved group; run this at STOP time to
    sanity-check the split before calling match()."""
    with open(csv_path) as f:
        ids = sorted({row["float_id"] for row in csv.DictReader(f)})
    counts = {"adaptation": 0, "calibration": 0, "test": 0}
    for fid in ids:
        counts[float_partition(fid, adaptation_share, calibration_share)] += 1
    counts["total_floats"] = len(ids)
    return counts


def match(run_path, csv_path, out, partition, max_km=30, max_days=1,
          adaptation_share=0.2, calibration_share=0.2):
    if partition not in ["calibration", "test"]:
        raise ValueError(
            "Use calibration or test; adaptation floats are reserved by "
            "float_partition() but this release has no adaptation match stage"
        )
    with xr.open_dataset(run_path) as f:
        ds = f.load()
    if ds.attrs.get("source_mode") == "synthetic":
        raise ValueError("Real observations cannot validate synthetic runs")
    if ds.attrs.get("partition") != partition:
        raise ValueError("Run partition must match observation partition")
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    matches = []
    times = ds.time.values.astype("datetime64[D]")
    for row in rows:
        fid = row["float_id"]
        # Three-way reservation: adaptation floats are silently excluded from
        # both calibration and test, not folded into whichever bucket asked.
        if float_partition(fid, adaptation_share, calibration_share) != partition:
            continue
        date = np.datetime64(row["date"])
        if np.isnat(date) or not np.isfinite([float(row[k]) for k in ["lat", "lon", "depth", "temperature"]]).all():
            raise ValueError("Invalid Argo observation coordinates, date or temperature")
        ti = int(np.argmin(abs(times - date)))
        if abs((times[ti] - date).astype(int)) > max_days:
            continue
        lat = float(row["lat"])
        lon = (float(row["lon"]) + 180) % 360 - 180
        yi = int(np.argmin(abs(ds.lat.values - lat)))
        xi = int(np.argmin(abs(ds.lon.values - lon)))
        km = 111.2 * np.hypot(
            float(ds.lat[yi]) - lat, (float(ds.lon[xi]) - lon) * np.cos(np.deg2rad(lat))
        )
        if km > max_km:
            continue
        z = float(row["depth"])
        zi = np.flatnonzero(DEPTHS == z)
        if not len(zi):
            continue
        prediction = float(ds.temperature.values[ti, zi[0], yi, xi])
        prior = float(ds.prior.values[ti, zi[0], yi, xi])
        if np.isfinite(prediction):
            matches.append(
                {
                    **row,
                    "depth": z,
                    "observed": float(row["temperature"]),
                    "predicted": prediction,
                    "prior": prior,
                    "distance_km": float(km),
                    "matched_date": str(times[ti]),
                }
            )
    if not matches:
        raise ValueError("No supported matchups; check bounds, split and QC")
    metrics = [
        {
            "depth": z,
            "model": score(
                [r["observed"] for r in matches if r["depth"] == z],
                [r["predicted"] for r in matches if r["depth"] == z],
            ),
            "climatology": score(
                [r["observed"] for r in matches if r["depth"] == z],
                [r["prior"] for r in matches if r["depth"] == z],
            ),
        }
        for z in DEPTHS
    ]
    result = {
        "source": "Argo",
        "partition": partition,
        "metrics": metrics,
        "matchups": matches,
        "float_ids": sorted(set(r["float_id"] for r in matches)),
        "run_sha256": sha256(run_path),
        "observations_sha256": sha256(csv_path),
        "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
        "model_fingerprint": ds.attrs.get("model_fingerprint"),
        "partition_fingerprint": scheme_fingerprint(PARTITION_SCHEME_VERSION, adaptation_share, calibration_share),
        "note": (
            "Held out from this model; teacher assimilation independence not "
            "established. Floats are reserved three ways (adaptation/"
            "calibration/test) via float_partition(); this file only "
            f"contains the requested '{partition}' group."
        ),
        "adaptation_share": adaptation_share,
        "calibration_share": calibration_share,
        "partition_scheme_version": PARTITION_SCHEME_VERSION,
    }
    dump(out, result)
    return result


def calibrate(matchups_path, out):
    obj = json.loads(Path(matchups_path).read_text())
    if obj["partition"] != "calibration" or obj["source"] != "Argo":
        raise ValueError("Use separate Argo calibration matchups")
    if obj.get("partition_scheme_version") != PARTITION_SCHEME_VERSION:
        raise ValueError(
            f"{matchups_path} was produced under a different float-partition "
            f"scheme (expected version {PARTITION_SCHEME_VERSION}). Regenerate "
            "it with match() against the current code before calibrating -- "
            "an old-scheme file can assign floats to different groups than "
            "match() would today, which would silently leak floats across "
            "adaptation/calibration/test."
        )
    validate_matchup_payload(obj, "Argo")
    if not obj.get("model_fingerprint") or not obj.get("partition_fingerprint"):
        raise ValueError("Regenerate calibration matchups with model and split fingerprints")
    # Common Argo support excludes 0 m; scope guarantees only to declared supported depths.
    depths = DEPTHS[DEPTHS >= 10]
    profiles = {}
    for row in obj["matchups"]:
        pid = row["profile_id"]
        profiles.setdefault(pid, {})[row["depth"]] = row["predicted"] - row["observed"]
    errors = np.array(
        [[p.get(float(z), np.nan) for z in depths] for p in profiles.values()]
    )
    cal = conformal(errors)
    cal.update(
        depths=depths.tolist(),
        float_ids=obj["float_ids"],
        last_date=max(r["date"] for r in obj["matchups"]),
        matchups_sha256=sha256(matchups_path),
        partition_scheme_version=PARTITION_SCHEME_VERSION,
        model_fingerprint=obj["model_fingerprint"],
        partition_fingerprint=obj["partition_fingerprint"],
        status="requires later-date, distinct-float coverage audit before display",
    )
    dump(out, cal)
    return cal
