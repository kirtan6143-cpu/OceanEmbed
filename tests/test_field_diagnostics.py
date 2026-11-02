import numpy as np
import pytest

from oceanembed.science import diagnostics, field_diagnostics


def test_field_diagnostics_matches_profile_diagnostics_cellwise():
    """A [depth, lat, lon] field of identical profiles must produce the same
    D26/TCHP/MLD-T at every cell as calling diagnostics() on one profile."""
    z = np.array([0, 10, 20, 30, 50, 100])
    t = np.array([28.0, 27.5, 26.5, 25.0, 20.0, 15.0])
    expected = diagnostics(z, t)
    field = np.tile(t[:, None, None], (1, 3, 4))
    out = field_diagnostics(z, field)
    assert np.allclose(out["d26_m"], expected["d26_m"])
    assert np.allclose(out["tchp_kj_cm2"], expected["tchp_kj_cm2"])
    assert np.allclose(out["mld_t_m"], expected["mld_t_m"])


def test_field_diagnostics_reports_nan_where_unbracketed():
    z = np.array([0, 10, 20])
    t = np.array([28.0, 27.0, 26.5])  # never crosses 26
    out = field_diagnostics(z, np.tile(t[:, None, None], (1, 2, 2)))
    assert np.isnan(out["d26_m"]).all()
    assert np.isnan(out["tchp_kj_cm2"]).all()


def test_field_diagnostics_rejects_mismatched_shape():
    with pytest.raises(ValueError):
        field_diagnostics([0, 10, 20], np.zeros((2, 3, 3)))
