import numpy as np
import pytest

from oceanembed import reliability as rel
from oceanembed.contracts import DEPTHS


def test_states_are_exactly_the_three_specified():
    assert rel.codes() == {0: "Supported", 1: "Caution", 2: "Abstain"}


def test_missing_value_abstains():
    v = np.array([[20.0, np.nan], [21.0, 22.0]])
    state, reason = rel.field_states(v, edge_cells=0)
    assert state[0, 1] == 2
    assert reason[0, 1] == "no_value"
    assert state[0, 0] == 0


def test_below_seabed_and_dry_cells_abstain():
    v = np.full((2, 2), 20.0)
    bathy = np.array([[500.0, 50.0], [-1.0, np.nan]])
    state, reason = rel.field_states(v, bathymetry=bathy, depth=100.0, edge_cells=0)
    assert state[0, 0] == 0            # seabed 500 m, depth 100 m -> fine
    assert reason[0, 1] == "below_seabed"   # seabed 50 m, depth 100 m
    assert reason[1, 0] == "dry_cell"       # non-positive depth
    assert reason[1, 1] == "dry_cell"       # non-finite bathymetry


def test_stale_inputs_downgrade_to_caution_not_abstain():
    v = np.full((2, 2), 20.0)
    age = np.full((3, 2, 2), 10.0)
    age[:, 0, 0] = 500.0  # far beyond the freshness limit
    state, reason = rel.field_states(v, age_hours=age, max_age_hours=48, edge_cells=0)
    assert state[0, 0] == 1
    assert reason[0, 0] == "stale_inputs"
    assert state[1, 1] == 0


def test_partial_channel_coverage_is_caution():
    v = np.full((2, 2), 20.0)
    age = np.full((3, 2, 2), 5.0)
    age[1, 0, 1] = np.nan  # one channel missing at one cell
    state, reason = rel.field_states(v, age_hours=age, edge_cells=0)
    assert state[0, 1] == 1
    assert reason[0, 1] == "partial_inputs"


def test_domain_edge_is_caution():
    v = np.full((9, 9), 20.0)
    state, reason = rel.field_states(v, edge_cells=2)
    assert state[0, 0] == 1
    assert reason[0, 0] == "domain_edge"
    assert state[4, 4] == 0  # interior stays Supported


def test_abstain_overrides_caution_precedence():
    """A stale AND dry cell must read Abstain, never Caution: structural
    absence of support outranks a freshness warning."""
    v = np.full((2, 2), 20.0)
    age = np.full((3, 2, 2), 999.0)
    bathy = np.full((2, 2), -1.0)
    state, reason = rel.field_states(
        v, bathymetry=bathy, depth=10.0, age_hours=age, edge_cells=0
    )
    assert (state == 2).all()
    assert (reason == "dry_cell").all()


def test_declared_support_mask_abstains():
    v = np.full((2, 2), 20.0)
    support = np.array([[1, 0], [1, 1]])
    state, reason = rel.field_states(v, support=support, edge_cells=0)
    assert state[0, 1] == 2
    assert reason[0, 1] == "unsupported_depth"


def test_summarize_counts_and_fraction():
    state = np.array([[0, 0], [1, 2]])
    s = rel.summarize(state)
    assert s["counts"] == {"Supported": 2, "Caution": 1, "Abstain": 1}
    assert s["evaluated_cells"] == 3
    assert s["supported_fraction_of_evaluated"] == pytest.approx(2 / 3)


def test_shallow_water_profile_reports_partial_coverage_not_blanket_abstain():
    """A profile in 400 m water legitimately has no 500/700/1000 m values.
    It must stay Supported for the levels it does report, with the reduced
    vertical coverage published rather than hidden."""
    t = np.full(len(DEPTHS), 20.0)
    t[-3:] = np.nan
    out = rel.profile_state(t, bathymetry=400.0)
    assert out["overall"] == "Supported"
    assert out["depths_reporting"] == 12
    assert out["depths_total"] == 15
    deep = [d for d in out["per_depth"] if d["depth"] == 1000.0][0]
    assert deep["state"] == "Abstain"
    assert deep["reason_code"] == "below_seabed"


def test_profile_overall_is_worst_live_state():
    """One stale level among otherwise-good levels drags the overall to
    Caution -- the worst live state wins, it is not averaged away."""
    t = np.full(len(DEPTHS), 20.0)
    out = rel.profile_state(t, bathymetry=2000.0, age_hours=np.full(7, 999.0))
    assert out["overall"] == "Caution"
    assert out["depths_reporting"] == 15


def test_profile_with_no_live_depths_abstains_overall():
    t = np.full(len(DEPTHS), np.nan)
    out = rel.profile_state(t, bathymetry=2000.0)
    assert out["overall"] == "Abstain"
    assert out["depths_reporting"] == 0


def test_profile_all_good_is_supported():
    t = np.full(len(DEPTHS), 20.0)
    out = rel.profile_state(t, bathymetry=2000.0, age_hours=np.full(7, 5.0))
    assert out["overall"] == "Supported"
    assert out["oldest_input_hours"] == 5.0


def test_calibration_reported_separately_from_state():
    """A Supported point on an uncalibrated run must not claim coverage."""
    t = np.full(len(DEPTHS), 20.0)
    uncalibrated = rel.profile_state(t, bathymetry=2000.0, calibrated=False)
    calibrated = rel.profile_state(t, bathymetry=2000.0, calibrated=True)
    assert uncalibrated["overall"] == "Supported"
    assert uncalibrated["calibration_applies"] is False
    assert calibrated["calibration_applies"] is True


def test_thresholds_are_published_with_every_profile():
    out = rel.profile_state(np.full(len(DEPTHS), 20.0), bathymetry=2000.0)
    t = out["thresholds"]
    assert t["gate_version"] == rel.GATE_VERSION
    assert t["states"] == ["Supported", "Caution", "Abstain"]


def test_field_states_rejects_non_2d():
    with pytest.raises(ValueError):
        rel.field_states(np.zeros((2, 2, 2)))


def test_field_states_rejects_negative_max_age():
    with pytest.raises(ValueError, match="positive"):
        rel.field_states(np.full((2, 2), 20.0), max_age_hours=-1)


def test_field_states_rejects_negative_edge_cells():
    with pytest.raises(ValueError, match="non-negative"):
        rel.field_states(np.full((2, 2), 20.0), edge_cells=-1)


def test_field_states_rejects_mismatched_support_shape():
    with pytest.raises(ValueError, match="support"):
        rel.field_states(np.full((2, 2), 20.0), support=[[1, 0]])


def test_field_states_rejects_mismatched_bathymetry_shape():
    with pytest.raises(ValueError, match="bathymetry"):
        rel.field_states(np.full((2, 2), 20.0), bathymetry=[[500.0]], depth=10.0)


def test_field_states_rejects_mismatched_age_hours_shape():
    with pytest.raises(ValueError, match="age_hours"):
        rel.field_states(np.full((2, 2), 20.0), age_hours=np.full((3, 3, 3), 5.0))


def test_profile_state_rejects_negative_max_age():
    t = np.full(len(DEPTHS), 20.0)
    with pytest.raises(ValueError, match="positive"):
        rel.profile_state(t, max_age_hours=0)


def test_profile_state_rejects_wrong_length_support():
    t = np.full(len(DEPTHS), 20.0)
    with pytest.raises(ValueError, match="one entry per depth"):
        rel.profile_state(t, support=[1, 0, 1])
