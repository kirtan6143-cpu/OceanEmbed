import copy
import numpy as np
import pytest
import xarray as xr
from oceanembed.contracts import save_nc, sha256
from oceanembed.rama import rama_to_csv, match, mooring_group


def _write_mooring(path, mooring_id, lat, lon, days, temp_20m, qc_ok=True):
    time = np.datetime64("2024-01-01") + np.arange(days)
    ds = xr.Dataset(
        {
            "T_20": (("time",), np.full(days, temp_20m), {"units": "degC"}),
            "T_20_QC": (("time",), np.full(days, 1 if qc_ok else 4, dtype=int)),
            "lat_var": ((), lat),
            "lon_var": ((), lon),
        },
        coords={"time": time},
        attrs={"site_id": mooring_id},
    )
    save_nc(ds, path)
    return ds


def _cfg(tmp_path):
    return {
        "reviewed": True,
        "path": str(tmp_path / "*.nc"),
        "mooring_id_attr": "site_id",
        "lat_var": "lat_var",
        "lon_var": "lon_var",
        "depth_variable": {20: "T_20"},
        "qc_variable": {20: "T_20_QC"},
        "accepted_qc": [1],  # ints on purpose: proves the str-normalization fix
    }


def test_reviewed_gate_matches_prepare_convention(tmp_path):
    _write_mooring(tmp_path / "m1.nc", "RAMA-1", 5.0, 90.0, 5, 28.0)
    cfg = _cfg(tmp_path)
    bad = copy.deepcopy(cfg)
    bad["reviewed"] = False
    with pytest.raises(ValueError, match="STOP 2"):
        rama_to_csv(bad, tmp_path / "rama.csv")


def test_rejects_depth_outside_contract_grid(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["depth_variable"] = {17: "T_20"}  # not one of the 15 contract depths
    with pytest.raises(ValueError, match="contract depths"):
        rama_to_csv(cfg, tmp_path / "rama.csv")


def test_qc_flag_excludes_bad_records(tmp_path):
    _write_mooring(tmp_path / "good.nc", "RAMA-1", 5.0, 90.0, 3, 28.0, qc_ok=True)
    _write_mooring(tmp_path / "bad.nc", "RAMA-2", 6.0, 91.0, 3, 99.0, qc_ok=False)
    n = rama_to_csv(_cfg(tmp_path), tmp_path / "rama.csv")
    assert n == 3  # only the QC-passing mooring's 3 days
    text = (tmp_path / "rama.csv").read_text()
    assert "RAMA-2" not in text


def test_match_reserves_moorings_by_group(tmp_path):
    _write_mooring(tmp_path / "m1.nc", "RAMA-1", 5.0, 90.0, 3, 28.0)
    _write_mooring(tmp_path / "m2.nc", "RAMA-2", 6.0, 91.0, 3, 27.5)
    rama_to_csv(_cfg(tmp_path), tmp_path / "rama.csv")

    from oceanembed.contracts import DEPTHS

    temp = np.full((3, len(DEPTHS), 3, 3), np.nan)
    temp[:, list(DEPTHS).index(20.0), :, :] = 28.0
    ds = xr.Dataset(
        {"temperature": (("time", "depth", "lat", "lon"), temp)},
        coords={
            "time": np.datetime64("2024-01-01") + np.arange(3),
            "depth": DEPTHS,
            "lat": [4.9, 5.5, 6.1],
            "lon": [89.9, 90.5, 91.1],
        },
        attrs={"source_mode": "research_blended", "partition": "test" if mooring_group("RAMA-1")=="held_out" else "validation"},
    )
    run = tmp_path / "run.nc"
    save_nc(ds, run)

    g1 = mooring_group("RAMA-1")
    g2 = mooring_group("RAMA-2")
    r1 = match(run, tmp_path / "rama.csv", tmp_path / "out1.json", g1)
    assert all(m["mooring_id"] == "RAMA-1" for m in r1["matchups"])
    assert r1["run_sha256"] == sha256(run)
    if g2 != g1:
        ds.attrs["partition"] = "test" if g2=="held_out" else "validation"
        save_nc(ds, run)
        r2 = match(run, tmp_path / "rama.csv", tmp_path / "out2.json", g2)
        assert all(m["mooring_id"] == "RAMA-2" for m in r2["matchups"])


def test_synthetic_run_refused(tmp_path):
    _write_mooring(tmp_path / "m1.nc", "RAMA-1", 5.0, 90.0, 3, 28.0)
    rama_to_csv(_cfg(tmp_path), tmp_path / "rama.csv")
    from oceanembed.contracts import DEPTHS

    temp = np.full((3, len(DEPTHS), 3, 3), np.nan)
    temp[:, list(DEPTHS).index(20.0), :, :] = 28.0
    ds = xr.Dataset(
        {"temperature": (("time", "depth", "lat", "lon"), temp)},
        coords={
            "time": np.datetime64("2024-01-01") + np.arange(3),
            "depth": DEPTHS,
            "lat": [4.9, 5.5, 6.1],
            "lon": [89.9, 90.5, 91.1],
        },
        attrs={"source_mode": "synthetic"},
    )
    run = tmp_path / "run.nc"
    save_nc(ds, run)
    with pytest.raises(ValueError, match="synthetic"):
        match(run, tmp_path / "rama.csv", tmp_path / "out.json", "development")
