import numpy as np
import yaml
from oceanembed.demo import create
from oceanembed.dataset import fit_transforms, split_indices, Windows


def _fixture(tmp_path):
    ds = create(tmp_path / "cube.nc")
    cfg = yaml.safe_load(open("configs/smoke.yaml"))
    tr = fit_transforms(ds, cfg, tmp_path / "tr.nc")
    return ds, tr, cfg


def test_train_crop_reproducible_within_epoch(tmp_path):
    ds, tr, cfg = _fixture(tmp_path)
    splits = split_indices(ds, cfg)
    w = Windows(ds, tr, splits["train"], cfg, cfg["patch"], vary_crops=True)
    a = w[0][0].copy()
    b = w[0][0].copy()
    np.testing.assert_array_equal(a, b)


def test_train_crop_changes_across_epochs(tmp_path):
    ds, tr, cfg = _fixture(tmp_path)
    splits = split_indices(ds, cfg)
    w = Windows(ds, tr, splits["train"], cfg, cfg["patch"], vary_crops=True)
    a = w[0][0].copy()
    w.set_epoch(1)
    b = w[0][0].copy()
    assert not np.array_equal(a, b)


def test_validation_crop_ignores_epoch(tmp_path):
    ds, tr, cfg = _fixture(tmp_path)
    splits = split_indices(ds, cfg)
    w = Windows(ds, tr, splits["validation"], cfg, cfg["patch"], vary_crops=False)
    a = w[0][0].copy()
    w.set_epoch(9)  # should have no effect when vary_crops is False
    b = w[0][0].copy()
    np.testing.assert_array_equal(a, b)
