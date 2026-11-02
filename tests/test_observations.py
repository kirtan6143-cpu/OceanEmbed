import pytest
from oceanembed.observations import float_partition


def test_partition_is_deterministic_and_three_way():
    ids = [f"590{i}" for i in range(500)]
    groups = {fid: float_partition(fid) for fid in ids}
    # Same float always lands in the same group, called any number of times.
    for fid in ids[:20]:
        assert float_partition(fid) == groups[fid]
    seen = set(groups.values())
    assert seen <= {"adaptation", "calibration", "test"}
    # With 500 floats and default shares, all three groups should be populated
    # (guards against an off-by-one collapsing a group to empty).
    assert len(seen) == 3


def test_partition_shares_are_disjoint_and_roughly_proportioned():
    ids = [f"49{i:04d}" for i in range(2000)]
    counts = {"adaptation": 0, "calibration": 0, "test": 0}
    for fid in ids:
        counts[float_partition(fid, adaptation_share=0.2, calibration_share=0.2)] += 1
    total = sum(counts.values())
    assert total == len(ids)
    # Loose bounds: hash bucketing should land within a few points of the
    # requested 20/20/60 split, not exactly on it.
    assert 0.15 < counts["adaptation"] / total < 0.25
    assert 0.15 < counts["calibration"] / total < 0.25
    assert 0.55 < counts["test"] / total < 0.65


def test_invalid_shares_rejected():
    with pytest.raises(ValueError):
        float_partition("5900001", adaptation_share=0.6, calibration_share=0.6)


def test_calibrate_rejects_stale_partition_scheme(tmp_path):
    import json
    from oceanembed.contracts import dump
    from oceanembed.observations import calibrate, PARTITION_SCHEME_VERSION

    matchups = tmp_path / "matchups.json"
    dump(
        matchups,
        {
            "source": "Argo",
            "partition": "calibration",
            "float_ids": ["590001"],
            "matchups": [
                {"date": "2024-01-01", "profile_id": "590001-1-0", "depth": 10,
                 "predicted": 20.0, "observed": 20.2}
            ],
            "partition_scheme_version": PARTITION_SCHEME_VERSION - 1,  # stale
        },
    )
    with pytest.raises(ValueError, match="partition"):
        calibrate(matchups, tmp_path / "cal.json")
