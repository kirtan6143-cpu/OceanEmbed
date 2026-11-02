import io
import numpy as np
import xarray as xr
from fastapi.testclient import TestClient
from oceanembed.demo import create
from oceanembed.cli import demo_run
from oceanembed.api import app, dataset


def test_api_selection_and_exports(tmp_path, monkeypatch):
    cube = tmp_path / "cube.nc"
    run = tmp_path / "run.nc"
    create(cube)
    demo_run(cube, run)
    monkeypatch.setenv("OCEAN_RUN", str(run))
    dataset.cache_clear()
    c = TestClient(app)
    meta = c.get("/runs").json()
    date = meta["dates"][0]
    params = {"date": date, "lat": 14, "lon": 88}
    p = c.get("/profile", params=params).json()
    assert len(p["temperature"]) == 15
    assert c.get("/field", params={"date": "1900-01-01"}).status_code == 404
    assert c.get("/profile", params={**params, "lat": 90}).status_code == 422
    assert c.get("/field", params={"date": date, "depth": 17}).status_code == 422
    assert c.get("/validation", params={"source": "Argo"}).json()["metrics"] == []
    assert c.get("/validation", params={"source": "RAMA"}).json()["metrics"] == []
    csv = c.get("/export", params={**params, "format": "csv"})
    assert "synthetic" in csv.text
    nc = c.get("/export", params={"date": date, "format": "netcdf"})
    with xr.open_dataset(io.BytesIO(nc.content), engine="h5netcdf") as ds:
        v = ds.temperature.sel(lat=p["lat"], lon=p["lon"]).values
        np.testing.assert_allclose(
            v, np.asarray(p["temperature"], dtype=float), equal_nan=True
        )
    assert (
        c.get("/export", params={"date": date, "format": "png"}).content[:8]
        == b"\x89PNG\r\n\x1a\n"
    )
    dataset.cache_clear()


def test_validation_serves_loaded_rama_results(tmp_path, monkeypatch):
    from oceanembed.contracts import dump, sha256

    cube = tmp_path / "cube.nc"
    run = tmp_path / "run.nc"
    create(cube)
    demo_run(cube, run)
    with xr.open_dataset(run) as f:
        real_fixture = f.load()
    real_fixture.attrs["source_mode"] = "research_blended"
    real_fixture.to_netcdf(run, engine="h5netcdf")
    rama_path = tmp_path / "rama.json"
    dump(
        rama_path,
        {
            "source": "RAMA",
            "observation_schema_version": 2,
            "group": "held_out",
            "metrics": [{"depth": 20.0, "model": {"n": 3, "rmse": 0.4}}],
            "matchups": [],
            "run_sha256": sha256(run),
        },
    )
    monkeypatch.setenv("OCEAN_RUN", str(run))
    monkeypatch.setenv("OCEAN_RAMA", str(rama_path))
    dataset.cache_clear()
    c = TestClient(app)
    body = c.get("/validation", params={"source": "RAMA"}).json()
    assert body["source"] == "RAMA"
    assert body["metrics"][0]["model"]["rmse"] == 0.4
    dataset.cache_clear()
