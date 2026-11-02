import json
import yaml
import numpy as np
from oceanembed.demo import create
from oceanembed.baseline import select, evaluate


def _cfg(tmp_path, cube):
    cfg = yaml.safe_load(open("configs/smoke.yaml"))
    cfg["cube"] = str(cube)
    return cfg


def test_select_output_unaffected_by_test_partition_content(tmp_path):
    """If select() ever started reading test data, corrupting it here would
    change chosen_lambda / validation_rmse. It must not."""
    cube = tmp_path / "cube.nc"
    ds = create(cube)
    cfg = _cfg(tmp_path, cube)

    select(cfg, tmp_path / "ridge_clean")
    clean = json.loads((tmp_path / "ridge_clean" / "selection.json").read_text())

    test_start, test_end = cfg["splits"]["test"]
    mask = (ds.time.values >= np.datetime64(test_start)) & (ds.time.values <= np.datetime64(test_end))
    ds["target"].values[mask] += 1000.0  # corrupt test-range values only
    ds["inputs"].values[mask] += 1000.0
    corrupted_cube = tmp_path / "cube_corrupted.nc"
    ds.to_netcdf(corrupted_cube, engine="h5netcdf")
    cfg_corrupt = _cfg(tmp_path, corrupted_cube)
    select(cfg_corrupt, tmp_path / "ridge_corrupt")
    corrupted = json.loads((tmp_path / "ridge_corrupt" / "selection.json").read_text())

    assert clean["lambda_selection"] == corrupted["lambda_selection"]
    assert "test" not in clean  # no test-derived numbers anywhere in the output
    assert not (tmp_path / "ridge_clean" / "metrics.json").exists()  # no report file yet


def test_evaluate_refuses_validation_reuse(tmp_path):
    cube = tmp_path / "cube.nc"
    create(cube)
    cfg = _cfg(tmp_path, cube)
    select(cfg, tmp_path / "ridge")
    try:
        evaluate(cfg, tmp_path / "ridge", tmp_path / "eval", partition="validation")
        assert False, "evaluate() must refuse to score on validation"
    except ValueError as e:
        assert "validation" in str(e)


def test_evaluate_scores_frozen_coefficients_on_test(tmp_path):
    cube = tmp_path / "cube.nc"
    create(cube)
    cfg = _cfg(tmp_path, cube)
    select(cfg, tmp_path / "ridge")
    evaluate(cfg, tmp_path / "ridge", tmp_path / "eval", partition="test")
    metrics = json.loads((tmp_path / "eval" / "metrics.json").read_text())
    assert metrics["stage"] == "evaluate"
    assert metrics["partition"] == "test"
    assert len(metrics["metrics"]) == 15
