"""Small shared observation rules, independent of NetCDF or the web framework."""
import hashlib
import json
import numpy as np

OBSERVATION_SCHEMA_VERSION = 2


def scalar_text(value):
    if isinstance(value, (bytes, np.bytes_)):
        return bytes(value).decode("utf-8").strip()
    return str(value).strip()


def qc_text(value):
    text = scalar_text(value)
    try:
        number = float(text)
        if np.isfinite(number) and number.is_integer():
            return str(int(number))
    except ValueError:
        pass
    return text


def to_celsius(values, units):
    unit = scalar_text(units).lower().replace(" ", "").replace("_", "")
    values = np.asarray(values, dtype=float)
    if unit in {"degc", "degreec", "degreesc", "celsius", "degreecelsius", "degreescelsius", "°c"}:
        result = values.copy()
    elif unit in {"k", "kelvin", "degreekelvin", "degreeskelvin"}:
        result = values - 273.15
    else:
        raise ValueError(f"Unsupported or missing temperature units: {units!r}")
    if np.isinf(result).any():
        raise ValueError("Infinite temperature values")
    return result


def scheme_fingerprint(version, adaptation_share=.2, calibration_share=.2, buckets=1000):
    if not isinstance(buckets, int) or buckets <= 0:
        raise ValueError("buckets must be a positive integer")
    if not np.isfinite([adaptation_share, calibration_share]).all():
        raise ValueError("Partition shares must be finite")
    if min(adaptation_share, calibration_share) < 0 or adaptation_share + calibration_share >= 1:
        raise ValueError("Partition shares must be nonnegative and leave a test group")
    payload = {"version": version, "adaptation_share": adaptation_share,
               "calibration_share": calibration_share, "buckets": buckets}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_matchup_payload(obj, source):
    if obj.get("source") != source:
        raise ValueError(f"Expected {source} evaluation")
    if obj.get("observation_schema_version") != OBSERVATION_SCHEMA_VERSION:
        raise ValueError("Observation schema changed; regenerate matchups with this release")
    for row in obj.get("matchups", []):
        for key in ["observed", "predicted", "depth"]:
            value = row.get(key)
            if value is None or not np.isfinite(float(value)):
                raise ValueError(f"Matchup has invalid {key}")
    return obj

