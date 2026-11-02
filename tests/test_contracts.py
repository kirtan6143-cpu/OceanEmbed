import numpy as np
import pytest
from oceanembed.demo import create
from oceanembed.contracts import validate_cube
from oceanembed.dataset import fit_transforms, split_indices
import yaml


def test_depth_masks_and_daily_axis(tmp_path):
    ds = create(tmp_path / "cube.nc")
    validate_cube(ds)
    ds.target.values[:, :, 0, 0] = 1
    ds.bathymetry.values[0, 0] = 0
    with pytest.raises(ValueError):
        validate_cube(ds)


def test_training_transforms_ignore_future(tmp_path):
    ds = create(tmp_path / "cube.nc")
    cfg = yaml.safe_load(open("configs/smoke.yaml"))
    tr = fit_transforms(ds, cfg, tmp_path / "tr.nc")
    future = ds.copy(deep=True)
    future["inputs"].values[365:] += 1000
    future["target"].values[365:] += 1000
    tr2 = fit_transforms(future, cfg, tmp_path / "tr2.nc")
    np.testing.assert_allclose(tr["mean"], tr2["mean"])
    np.testing.assert_allclose(tr.climatology, tr2.climatology, equal_nan=True)
    splits = split_indices(ds, cfg)
    assert not set(splits["train"]).intersection(splits["test"])
