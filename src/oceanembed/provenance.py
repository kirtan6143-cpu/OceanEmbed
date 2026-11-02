"""Run-identity fingerprints (V2 audit item 9).

Deterministic, dependency-light helpers so every artifact can be tied to the
exact grid, source cube, data split and model that produced a run. They never
alter scientific values.
"""

import hashlib
import json
from pathlib import Path

import numpy as np

from .contracts import sha256

# Attributes a real run must inherit from its prepared cube so the release
# verifier can confirm how the 0 m level was produced.
INHERITED_CUBE_ATTRS = (
    "surface_convention",
    "surface_tolerance_m",
    "temperature_convention",
    "availability_mode",
)


def _array_digest(h, name, values):
    arr = np.asarray(values)
    if arr.dtype.kind in "fc":
        arr = np.round(arr.astype("float64"), 6)
        payload = arr.tobytes()
    else:
        payload = json.dumps([str(v) for v in arr.ravel()]).encode()
    h.update(name.encode())
    h.update(str(arr.shape).encode())
    h.update(payload)


def grid_fingerprint(ds):
    """Hash of the lat/lon/depth/channel coordinates (not the data)."""
    h = hashlib.sha256()
    for name in ("lat", "lon", "depth", "channel"):
        if name in ds.coords:
            _array_digest(h, name, ds[name].values)
    return h.hexdigest()


def json_fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def file_or_none(path):
    p = Path(path)
    return sha256(p) if p.exists() else None


def inherited_attrs(cube_attrs):
    return {k: cube_attrs[k] for k in INHERITED_CUBE_ATTRS if k in cube_attrs}
