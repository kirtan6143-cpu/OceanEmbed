import csv
import numpy as np
import pytest
import xarray as xr

from oceanembed.contracts import DEPTHS, save_nc
from oceanembed.cyclone import load_track, thermal_context, cold_wake


def write_track(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["STORM_NAME", "ISO_TIME", "LAT", "LON", "WIND_KT", "GRADE"]
        )
        w.writeheader()
        w.writerows(rows)
    return path


def track_rows(name="TESTSTORM", lat=14.0, lon=88.0, days=6, start="2024-01-05"):
    d0 = np.datetime64(start)
    return [
        {
            "STORM_NAME": name,
            "ISO_TIME": str(d0 + np.timedelta64(i, "D")),
            "LAT": lat + i * 0.1,
            "LON": lon + i * 0.1,
            "WIND_KT": 60 + i,
            "GRADE": "Very Severe Cyclonic Storm",
        }
        for i in range(days)
    ]


def base_spec(path):
    return {
        "reviewed": True,
        "path": str(path),
        "columns": {
            "name": "STORM_NAME",
            "datetime": "ISO_TIME",
            "lat": "LAT",
            "lon": "LON",
            "max_wind": "WIND_KT",
            "category": "GRADE",
        },
        "wind_averaging": "3-minute sustained",
        "category_scheme": "IMD",
        "source": "test fixture",
    }


def make_run(path, days=14, start="2024-01-01", temp=28.0, cool_after=None):
    """Grid covering the track, warm enough that D26 exists."""
    time = np.datetime64(start) + np.arange(days)
    lat = np.linspace(10, 20, 12)
    lon = np.linspace(84, 94, 12)
    profile = np.linspace(temp, 5.0, len(DEPTHS))
    values = np.tile(
        profile[None, :, None, None], (days, 1, len(lat), len(lon))
    ).astype(float)
    if cool_after is not None:
        after = time > np.datetime64(cool_after)
        values[after] -= 2.0
    ds = xr.Dataset(
        {
            "temperature": (("time", "depth", "lat", "lon"), values),
            "bathymetry": (("lat", "lon"), np.full((len(lat), len(lon)), 3000.0)),
        },
        coords={"time": time, "depth": DEPTHS, "lat": lat, "lon": lon},
        attrs={"source_mode": "research_blended"},
    )
    save_nc(ds, path)
    return path


def test_unreviewed_config_refuses(tmp_path):
    spec = base_spec(write_track(tmp_path / "t.csv", track_rows()))
    spec["reviewed"] = False
    with pytest.raises(ValueError, match="STOP 2"):
        load_track(spec)


def test_mapped_wind_requires_averaging_period(tmp_path):
    spec = base_spec(write_track(tmp_path / "t.csv", track_rows()))
    spec.pop("wind_averaging")
    with pytest.raises(ValueError, match="wind_averaging"):
        load_track(spec)


def test_mapped_category_requires_scheme(tmp_path):
    spec = base_spec(write_track(tmp_path / "t.csv", track_rows()))
    spec.pop("category_scheme")
    with pytest.raises(ValueError, match="category_scheme"):
        load_track(spec)


def test_category_label_preserved_verbatim(tmp_path):
    track = load_track(base_spec(write_track(tmp_path / "t.csv", track_rows())))
    assert track["points"][0]["category"] == "Very Severe Cyclonic Storm"
    assert track["category_scheme"] == "IMD"
    assert track["wind_averaging"] == "3-minute sustained"


def test_multiple_storms_in_one_file_rejected(tmp_path):
    rows = track_rows(name="ALPHA") + track_rows(name="BETA")
    with pytest.raises(ValueError, match="multiple storms"):
        load_track(base_spec(write_track(tmp_path / "t.csv", rows)))


def test_missing_required_column_mapping_rejected(tmp_path):
    spec = base_spec(write_track(tmp_path / "t.csv", track_rows()))
    del spec["columns"]["lat"]
    with pytest.raises(ValueError, match="missing"):
        load_track(spec)


def test_track_points_sorted_by_time(tmp_path):
    rows = list(reversed(track_rows()))
    track = load_track(base_spec(write_track(tmp_path / "t.csv", rows)))
    stamps = [p["datetime"] for p in track["points"]]
    assert stamps == sorted(stamps)


def test_thermal_context_reports_d26_and_tchp(tmp_path):
    track = load_track(base_spec(write_track(tmp_path / "t.csv", track_rows())))
    run = make_run(tmp_path / "run.nc")
    result = thermal_context(run, track)
    assert result["points_with_thermal_context"] > 0
    covered = [p for p in result["points"] if p["d26_m"] is not None]
    assert all(p["tchp_kj_cm2"] is not None for p in covered)
    assert "not an intensity" in result["limits"].lower()


def test_out_of_domain_points_reported_not_dropped(tmp_path):
    rows = track_rows(lat=14.0, lon=88.0, days=3) + track_rows(
        lat=60.0, lon=150.0, days=2, start="2024-01-08"
    )
    for r in rows:
        r["STORM_NAME"] = "TESTSTORM"
    track = load_track(base_spec(write_track(tmp_path / "t.csv", rows)))
    result = thermal_context(make_run(tmp_path / "run.nc"), track)
    assert result["points_total"] == 5
    reasons = [p["reason"] for p in result["points"] if p["reason"]]
    assert any("Outside run domain" in r for r in reasons)


def test_dates_outside_run_reported(tmp_path):
    track = load_track(
        base_spec(write_track(tmp_path / "t.csv", track_rows(start="2025-06-01")))
    )
    result = thermal_context(make_run(tmp_path / "run.nc"), track)
    assert result["points_with_thermal_context"] == 0
    assert all(p["reason"] == "Date not in run" for p in result["points"])


def test_cold_wake_detects_a_real_cooling(tmp_path):
    """Run cools by 2 C after 2024-01-08; a track passing on 01-09 with
    complete windows on both sides must report a negative change."""
    track = load_track(
        base_spec(write_track(tmp_path / "t.csv", track_rows(start="2024-01-09", days=1)))
    )
    run = make_run(tmp_path / "run.nc", days=20, cool_after="2024-01-08")
    result = cold_wake(run, track, depth=50.0, days=3)
    usable = [r for r in result["records"] if r["change_degC"] is not None]
    assert usable, "expected at least one complete pre/post window"
    assert result["mean_change_degC"] == pytest.approx(-2.0, abs=1e-6)


def test_cold_wake_requires_complete_windows_on_both_sides(tmp_path):
    """A passage on the run's first day has no pre-passage window and must
    yield no value with a stated reason, not a one-sided average."""
    track = load_track(
        base_spec(write_track(tmp_path / "t.csv", track_rows(start="2024-01-01", days=1)))
    )
    result = cold_wake(make_run(tmp_path / "run.nc"), track, depth=50.0, days=3)
    assert result["locations_with_complete_windows"] == 0
    assert all("Incomplete" in r["reason"] for r in result["records"])


def test_cold_wake_rejects_non_contract_depth(tmp_path):
    track = load_track(base_spec(write_track(tmp_path / "t.csv", track_rows())))
    with pytest.raises(ValueError, match="contract depths"):
        cold_wake(make_run(tmp_path / "run.nc"), track, depth=17.0)


def test_cold_wake_deduplicates_repeated_cells(tmp_path):
    """Several track points snapping to the same grid cell on the same day
    must produce one record, not one per point."""
    rows = track_rows(lat=14.0, lon=88.0, days=1)
    rows = rows * 3
    for i, r in enumerate(rows):
        r["LAT"] = 14.0 + i * 0.001  # all snap to the same coarse cell
    track = load_track(base_spec(write_track(tmp_path / "t.csv", rows)))
    result = cold_wake(
        make_run(tmp_path / "run.nc", days=20), track, depth=50.0, days=2
    )
    assert result["locations_total"] == 1
