import numpy as np
import pytest
from oceanembed.science import diagnostics, heat_events, conformal, score


def test_heat_content_linear_profile():
    r = diagnostics([0, 10, 20, 50, 100], [28, 27.6, 27.2, 26, 24])
    assert r["d26_m"] == 50
    assert r["tchp_kj_cm2"] == pytest.approx(1025 * 3990 * 50 / 1e7)
    assert r["mld_t_m"] == pytest.approx(15)


def test_missing_bracket_and_cold_surface():
    assert diagnostics([0, 10, 100], [28, np.nan, 20])["d26_m"] is None
    assert diagnostics([0, 10, 100], [25, 24, 20])["tchp_kj_cm2"] == 0


def test_event_persistence_and_gap():
    dates = np.datetime64("2024-01-01") + np.arange(7)
    assert len(heat_events(dates, [28] * 7, 26, 27)) == 1
    assert heat_events(dates, [28, 28, 28, 28, np.nan, 28, 28], 26, 27) == []
    assert heat_events(dates, [27] * 7, 26, 27) == []


def test_conformal_rank():
    a = np.arange(1, 20)[:, None] * np.ones((1, 3))
    assert conformal(a, alpha=0.1)["q_degC"] == 18
    with pytest.raises(ValueError):
        conformal(np.ones((2, 3)), alpha=0.1)


def test_masked_metrics():
    r = score([1, np.nan, 3], [2, 100, 3])
    assert r["n"] == 2
    assert r["bias"] == 0.5


def test_pdf_canonical_example():
    """Locked reference case from the implementation guide, section 10:
    T(z) = 30 - 0.1z over 0-100 m -> D26=40m, warm-layer integral=80 C.m,
    TCHP=32.718 kJ/cm2, MLD-T=12m. These are the spec's own unit-check
    values, not a re-derivation of them."""
    z = np.arange(101.0)
    t = 30 - 0.1 * z
    r = diagnostics(z, t)
    assert r["d26_m"] == pytest.approx(40, abs=1e-9)
    assert r["tchp_kj_cm2"] == pytest.approx(32.718, abs=1e-3)
    assert r["mld_t_m"] == pytest.approx(12, abs=1e-9)
